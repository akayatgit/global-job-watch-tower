from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import deploy_status


class DeployStatusTests(unittest.TestCase):
    def test_running_sha_is_immutable_process_start_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            stamp = Path(tmp) / 'last_deploy.json'
            stamp.write_text(
                '{"sha":"abc123","status":"ok","deployed_at":"now"}',
                encoding='utf-8',
            )
            with (
                patch.object(deploy_status, 'STAMP_FILE', stamp),
                patch.dict(os.environ, {'WATCH_TOWER_RUNTIME_SHA': 'abc123'}),
                patch.object(deploy_status, '_git_head', return_value='different-working-tree'),
            ):
                status = deploy_status.compute_deploy_status()
        self.assertEqual(status['running_sha'], 'abc123')
        self.assertTrue(status['in_sync'])


if __name__ == '__main__':
    unittest.main()
