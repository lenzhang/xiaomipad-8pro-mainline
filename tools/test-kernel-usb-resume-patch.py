#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The Type-C host resume patch matches its lock and applies onto the pinned kernel."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import unittest

REPO = Path(__file__).resolve().parents[1]
LOCK = REPO / 'kernel/source.json'
PATCH = REPO / 'kernel/patches/0001-usb-dwc3-host-resume-reenumerate.patch'


class HostResumePatch(unittest.TestCase):
    def test_patch_is_a_host_reenumeration_fix(self):
        # The patch is not applied by the kernel builder: piano58's commit and
        # config stay the packaged ABI. This only checks the patch itself.
        text = PATCH.read_text()
        self.assertIn('resume_host_lost_power', text)
        self.assertIn('power_lost', text)
        self.assertIn('PHY_MODE_USB_HOST', text)
        self.assertNotIn('Signed-off-by:', text)
        self.assertEqual(hashlib.sha256(PATCH.read_bytes()).hexdigest(),
                         '0917ad5b2183f5425d550f67bc2c1d0466a77598ee11ecb150e677a524ada86e')

    def test_patch_applies_to_the_pinned_commit(self):
        source = os.environ.get('KERNEL_SOURCE')
        if not source:
            self.skipTest('KERNEL_SOURCE is not set')
        root = Path(source)
        commit = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
        self.assertEqual(commit, json.loads(LOCK.read_text())['commit'])
        dirty = subprocess.check_output(
            ['git', '-C', str(root), 'status', '--porcelain', '--untracked-files=no'], text=True)
        self.assertEqual(dirty, '')
        subprocess.run(['git', '-C', str(root), 'apply', '--check', str(PATCH)], check=True)


if __name__ == '__main__':
    unittest.main()
