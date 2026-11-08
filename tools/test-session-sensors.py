#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Policy tests for the piano session sensor client. No D-Bus and no hardware."""
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
import tempfile
import unittest

PATH = Path(__file__).resolve().parents[1] / 'packaging/piano-ubuntu-desktop/usr/libexec/piano/session-sensors'
LOADER = SourceFileLoader('session_sensors', str(PATH))
SPEC = importlib.util.spec_from_loader('session_sensors', LOADER)
sensors = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(sensors)


def bits(positions, word_bits=64):
    words = []
    for bit in positions:
        index = bit // word_bits
        while len(words) <= index:
            words.append(0)
        words[index] |= 1 << (bit % word_bits)
    return ' '.join(f'{word:x}' for word in reversed(words))


class Bitmap(unittest.TestCase):
    def test_low_and_high_bits(self):
        self.assertTrue(sensors.bitmap_has('2', 1))
        self.assertFalse(sensors.bitmap_has('2', 0))
        self.assertTrue(sensors.bitmap_has(bits([0x35]), 0x35))
        self.assertFalse(sensors.bitmap_has(bits([0x35]), 0x36))
        self.assertFalse(sensors.bitmap_has('', 0))


class Seat(unittest.TestCase):
    def test_detached_tablet_and_docked_keyboard(self):
        touch = {'touchscreen': True, 'pointer': False, 'tablet_switch': False}
        self.assertTrue(sensors.touch_mode([touch]))
        switch = {'touchscreen': False, 'pointer': False, 'tablet_switch': True, 'switch_on': True}
        self.assertTrue(sensors.touch_mode([touch, switch]))
        switch['switch_on'] = False
        pad = {'touchscreen': False, 'pointer': True, 'tablet_switch': False}
        self.assertFalse(sensors.touch_mode([touch, switch, pad]))
        switch['switch_on'] = None
        self.assertIsNone(sensors.touch_mode([touch, switch]))
        self.assertFalse(sensors.touch_mode([pad]))
        self.assertIsNone(sensors.touch_mode([]))

    def test_classification_matches_direct_panel_and_pointer(self):
        panel = sensors.classify_device(bits([sensors.INPUT_PROP_DIRECT]), bits([sensors.ABS_MT_POSITION_X]), '', '')
        self.assertTrue(panel['touchscreen'])
        self.assertFalse(panel['pointer'])
        mouse = sensors.classify_device(bits([sensors.INPUT_PROP_POINTER]), '', bits([sensors.REL_X]), '')
        self.assertTrue(mouse['pointer'])
        self.assertFalse(mouse['touchscreen'])
        folio = sensors.classify_device('', '', '', bits([sensors.SW_TABLET_MODE]))
        self.assertTrue(folio['tablet_switch'])
        self.assertFalse(folio['touchscreen'])


class Orientation(unittest.TestCase):
    def test_transform_policy(self):
        self.assertEqual(sensors.desired_transform(True, False, 'left-up'), 1)
        self.assertEqual(sensors.desired_transform(True, False, 'bottom-up'), 2)
        self.assertEqual(sensors.desired_transform(True, False, 'right-up'), 3)
        self.assertEqual(sensors.desired_transform(True, False, 'normal'), 0)
        self.assertIsNone(sensors.desired_transform(True, True, 'left-up'))
        self.assertEqual(sensors.desired_transform(False, False, 'left-up'), 0)
        self.assertIsNone(sensors.desired_transform(None, False, 'left-up'))
        self.assertIsNone(sensors.desired_transform(True, False, 'undefined'))

    def test_only_builtin_transform_changes(self):
        monitors = [
            (('DSI-1', '', '', ''), [('3200x2136@60', 3200, 2136, 60, 2, [2], {'is-current': True})],
             {'is-builtin': True}),
            (('DP-1', '', '', ''), [('3840x2160@60', 3840, 2160, 60, 1, [1], {'is-current': True})], {}),
        ]
        logical = [
            (0, 0, 2.0, 0, True, [('DSI-1', '', '', '')], {}),
            (1600, 0, 1.0, 0, False, [('DP-1', '', '', '')], {}),
        ]
        changed, planned = sensors.orientation_config(monitors, logical, 1)
        self.assertTrue(changed)
        self.assertEqual(planned[0][3], 1)
        self.assertEqual(planned[0][2], 2.0)
        self.assertEqual(planned[0][5], [('DSI-1', '3200x2136@60', {})])
        self.assertEqual(planned[1][3], 0)
        self.assertEqual(planned[1][0], 1600)
        again, _planned = sensors.orientation_config(monitors, [
            (0, 0, 2.0, 1, True, [('DSI-1', '', '', '')], {}),
            logical[1],
        ], 1)
        self.assertFalse(again)

    def test_single_unmarked_panel_is_the_builtin(self):
        monitors = [(('DSI-1', '', '', ''), [('mode', 1, 1, 60, 1, [1], {'is-current': True})], {})]
        logical = [(0, 0, 2.0, 0, True, [('DSI-1', '', '', '')], {})]
        changed, planned = sensors.orientation_config(monitors, logical, 2)
        self.assertTrue(changed)
        self.assertEqual(planned[0][3], 2)


class Ambient(unittest.TestCase):
    def test_first_sample_normalizes_and_holds_until_the_interval(self):
        ambient = sensors.Ambient()
        self.assertIsNone(ambient.update(100.0, 0))
        self.assertAlmostEqual(ambient.norm_value, 150.0)
        self.assertIsNone(ambient.update(100.0, 50_000))
        target = ambient.update(100.0, 100_000)
        self.assertAlmostEqual(target, ambient.accumulator / 100.0)
        ambient.user_changed()
        ambient.update(200.0, 200_000)
        self.assertAlmostEqual(ambient.norm_value, 300.0)

    def test_non_positive_light_does_not_move_the_target(self):
        ambient = sensors.Ambient()
        self.assertIsNone(ambient.update(0, 0))
        self.assertIsNone(ambient.update(None, 1))
        self.assertTrue(ambient.norm_required)


class Sysfs(unittest.TestCase):
    def test_switch_state_comes_from_the_caller(self):
        with tempfile.TemporaryDirectory() as tmp:
            event = Path(tmp) / 'event3' / 'device'
            (event / 'capabilities').mkdir(parents=True)
            (event / 'properties').write_text(bits([sensors.INPUT_PROP_DIRECT]) + '\n')
            (event / 'capabilities/abs').write_text(bits([sensors.ABS_MT_POSITION_X]) + '\n')
            (event / 'capabilities/rel').write_text('0\n')
            (event / 'capabilities/sw').write_text(bits([sensors.SW_TABLET_MODE]) + '\n')
            devices = sensors.load_devices(tmp, lambda name: {'event3': False}[name])
            self.assertEqual(len(devices), 1)
            self.assertTrue(devices[0]['touchscreen'])
            self.assertTrue(devices[0]['tablet_switch'])
            self.assertFalse(devices[0]['switch_on'])
            self.assertFalse(sensors.touch_mode(devices))


if __name__ == '__main__':
    unittest.main()
