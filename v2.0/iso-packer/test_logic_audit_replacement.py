"""Stateful safety regressions for source ownership and version replacement."""
import copy
from contextlib import ExitStack
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import app


class ArtifactOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'watch' / 'Mercy.2026.V2.2160p.BluRay@CHDBits'
        (self.source / 'BDMV').mkdir(parents=True)
        self.media = self.source / 'BDMV' / 'index.bdmv'
        self.media.write_bytes(b'source')
        self.output = self.root / 'output'
        self.output.mkdir()
        self.cloud = self.root / 'cloud'
        self.cloud.mkdir()
        self.target = self.output / (self.source.name + '.iso')
        self.old = self.cloud / 'Mercy.2026.V1.2160p.BluRay@CHDBits.iso'
        self.old.write_bytes(b'old complete ISO')
        self.cfg = copy.deepcopy(app.DEFAULT_CONFIG)
        self.cfg.update(watch_dir=str(self.source.parent), output_dir=str(self.output),
                        cd2_mount_root=str(self.cloud), cd2_target_dir=str(self.cloud),
                        cd2_require_mount=False, cd2_transfer_enabled=True,
                        cd2_wait_upload_complete=True, delete_source_after_success=True)
        self.data = {'items': {}, 'active': None, 'events': [], 'cd2': {}}
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        for name, value in {'state': self.data, '_process_config': None,
                            'save_state_locked': lambda: None, 'log': lambda *_: None,
                            'fetch_cd2_uploads': lambda *_: ({}, {'connected': False}),
                            'source_readiness_blocker': lambda *a, **kw: (None, None, None),
                            'should_pack_iso': lambda *_: (True, 'ready'),
                            'enough_space': lambda *_: True, 'validate_iso': lambda *_: True,
                            'run_iso': self.pack, 'transfer_iso_to_mount': self.transfer}.items():
            self.patches.enter_context(patch.object(app, name, value))

    def pack(self, source, target, size):
        target.write_bytes(b'valid new ISO')
        return SimpleNamespace(returncode=0, stderr='')

    def transfer(self, target, cfg):
        final = self.cloud / target.name
        app.begin_cd2_upload_claim(self.source, final, cfg, target.stat().st_size)
        final.write_bytes(target.read_bytes())
        return final

    def finish(self):
        final = self.cloud / self.target.name
        for index, enum in enumerate(('3', '5')):
            upload = {'key': 'new-upload', 'path': str(final), 'total': final.stat().st_size,
                      'status_enum': enum, 'status': 'Transfer' if enum == '3' else 'Finish'}
            app.check_waiting_cd2_uploads(self.cfg, {str(final): upload},
                                        {'connected': True, 'checked_at': f'check-{index}', 'upload_queue_complete': True})

    def test_unowned_valid_existing_iso_never_deletes_the_current_source(self):
        self.target.write_bytes(b'valid but unrelated ISO')
        self.cfg['cd2_transfer_enabled'] = False
        app.process_item(self.source, self.cfg)
        self.assertTrue(self.source.exists())
        self.assertTrue(self.target.exists())
        self.assertEqual(self.data['items'][str(self.source)].get('failure_code'), 'output_exists')

    def test_source_changed_during_pack_is_retained_and_not_uploaded(self):
        def changed(source, target, size):
            result = self.pack(source, target, size)
            self.media.write_bytes(b'new source content')
            return result
        with patch.object(app, 'run_iso', side_effect=changed), patch.object(app, 'transfer_iso_to_mount') as transfer:
            app.process_item(self.source, self.cfg)
        transfer.assert_not_called()
        self.assertTrue(self.source.exists())
        self.assertEqual(self.data['items'][str(self.source)].get('failure_code'), 'source_changed')

    def test_old_version_remains_until_the_new_upload_explicitly_finishes(self):
        app.process_item(self.source, self.cfg)
        self.assertEqual(self.data['items'][str(self.source)]['status'], 'waiting_cd2_upload')
        self.assertTrue(self.old.exists())
        self.finish()
        self.assertEqual(self.data['items'][str(self.source)]['status'], 'transfer_done')
        self.assertFalse(self.old.exists())

    def test_replaced_old_candidate_is_not_deleted_after_waiting(self):
        app.process_item(self.source, self.cfg)
        self.old.write_bytes(b'replaced with unrelated file')
        self.finish()
        self.assertTrue(self.old.exists())

    def test_source_signature_tracks_changes_below_a_future_dated_file(self):
        future = self.source / 'BDMV' / 'future.bdmv'
        future.write_bytes(b'future')
        future_ns = 2_000_000_000_000_000_000
        os.utime(future, ns=(future_ns, future_ns))
        before = app.tree_signature(self.source)
        self.media.write_bytes(b'changed source data')
        self.assertNotEqual(before, app.tree_signature(self.source))

    def test_source_changed_during_transfer_is_retained_after_finish(self):
        def changed(target, cfg):
            result = self.transfer(target, cfg)
            self.media.write_bytes(b'changed during transfer')
            return result
        with patch.object(app, 'transfer_iso_to_mount', side_effect=changed):
            app.process_item(self.source, self.cfg)
        self.finish()
        self.assertTrue(self.source.exists())
        self.assertTrue(self.target.exists())
        self.assertTrue(self.old.exists())
        self.assertEqual(self.data['items'][str(self.source)].get('failure_code'), 'source_changed')

    def test_owned_local_iso_cannot_authorize_deleting_unowned_recovery_target(self):
        self.target.write_bytes(b'valid local ISO')
        app.record_output_provenance(self.source, self.target)
        cloud = self.cloud / self.target.name
        cloud.write_bytes(b'unrelated invalid ISO')
        active = {'source': str(self.source), 'target': str(cloud), 'output_target': str(self.target)}
        with patch.object(app, 'validate_iso', side_effect=lambda path: path == self.target):
            app.finish_recovered_iso(self.source, cloud, self.cfg, active)
        self.assertTrue(cloud.exists())
        self.assertTrue(self.source.exists())
        self.assertTrue(self.target.exists())
        self.assertEqual(self.data['items'][str(self.source)].get('failure_code'), 'target_exists')

    def test_legacy_recovery_without_provenance_preserves_source_and_iso(self):
        self.target.write_bytes(b'legacy ISO')
        active = {'source': str(self.source), 'target': str(self.target)}
        app.finish_recovered_iso(self.source, self.target, self.cfg, active)
        self.assertTrue(self.source.exists())
        self.assertTrue(self.target.exists())
        self.assertEqual(self.data['items'][str(self.source)].get('failure_code'), 'recovery_unverified')

    def test_concurrent_preflight_cannot_clear_another_active_pack(self):
        entered, release = threading.Event(), threading.Event()
        def pack(source, target, size):
            entered.set()
            if not release.wait(2):
                raise AssertionError('test did not release pack')
            return self.pack(source, target, size)
        with patch.object(app, 'run_iso', side_effect=pack):
            worker = threading.Thread(target=app.process_item, args=(self.source, self.cfg))
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                active = copy.deepcopy(self.data['active'])
                app.process_item(self.source, self.cfg)
                self.assertEqual(self.data['active'], active)
            finally:
                release.set()
                worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.data['items'][str(self.source)]['status'], 'waiting_cd2_upload')

    def test_cancelled_mid_pack_restart_without_final_iso_can_rescan(self):
        active = {'source': str(self.source), 'target': str(self.target)}
        self.assertFalse(app.finish_recovered_iso(self.source, self.target, self.cfg, active))
        self.assertNotIn(str(self.source), self.data['items'])

    def test_manual_confirmation_cannot_finish_a_new_pack_generation(self):
        app.process_item(self.source, self.cfg)
        final = self.cloud / self.target.name
        def rerun_during_validation(_target):
            app.start_process_item_task(self.source, self.target, app.size_of(self.source), app.now())
            return True
        with patch.object(app, 'validate_iso', side_effect=rerun_during_validation):
            result, status = app.confirm_cd2_upload_task(str(self.source), self.cfg)
        self.assertEqual(status, 409)
        self.assertFalse(result['ok'])
        self.assertEqual(self.data['items'][str(self.source)]['status'], 'running')
        self.assertTrue(self.source.exists())
        self.assertTrue(self.target.exists())
        self.assertTrue(final.exists())


if __name__ == '__main__':
    unittest.main()
