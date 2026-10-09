import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

from exploration import ExpansionCatalog
from worker import Worker

FIXTURES = Path(__file__).parent / 'fixtures'


def screen_with_logo(name, y=.60):
    screen = Image.new('RGB', (1206, 2622), 'white')
    with Image.open(FIXTURES / (name + '.png')) as logo:
        screen.paste(logo, (int(1206 * .14), int(2622 * (y - .115))))
    return screen


class ExplorationTests(unittest.TestCase):
    def test_same_expansion_survives_ocr_jitter_and_scroll(self):
        catalog = ExpansionCatalog()
        first = catalog.identify(screen_with_logo('expansion-ex'), {'y': .60}, 'Aシリーズ', 30)
        for y, jitter in [(.60, .005), (.60, -.009), (.72, .012)]:
            identity = catalog.identify(screen_with_logo('expansion-ex', y),
                                        {'y': y + jitter}, 'Aシリーズ', 30)
            self.assertEqual(identity, first)

    def test_different_logos_with_same_total_have_different_ids(self):
        catalog = ExpansionCatalog()
        first = catalog.identify(screen_with_logo('expansion-ex'), {'y': .60}, 'Aシリーズ', 30)
        second = catalog.identify(screen_with_logo('expansion-water'), {'y': .60}, 'Aシリーズ', 30)
        self.assertNotEqual(first, second)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.addCleanup(patch.stopall)
        patch('worker.ROOT', root).start()
        patch('worker.SESSION_FILE', Mock(read_text=Mock(return_value='test'))).start()
        patch('worker.request', return_value={'value': {'bundleId': 'jp.pokemon.pokemontcgp'}}).start()
        patch('worker.Device', return_value=Mock(unlock=Mock(return_value=False),
                                               wait_foreground=Mock(return_value=False))).start()
        self.worker = Worker(0, 900)
        self.worker.tap = Mock()
        self.worker.swipe = Mock()
        self.worker.log = Mock()
        self.worker.reward_color = Mock(return_value=0)
        self.rows = []

        def observe(path):
            Image.new('RGB', (1206, 2622), 'white').save(path)
            return self.rows

        patch('worker.observe', side_effect=observe).start()

    @staticmethod
    def row(text, x=.5, y=.6):
        return {'text': text, 'x': x, 'y': y, 'height': .02}

    def popup(self):
        return [self.row('エキスパンション選択', y=.15),
                self.row('Aシリーズ', x=.58, y=.84),
                self.row('Bシリーズ', x=.22, y=.84),
                self.row('3/30', y=.60)]

    def test_exhausted_expansion_is_not_reselected_on_return(self):
        w = self.worker
        w.series_initialized = True
        w.expansion_catalog.identify = Mock(return_value=7)
        w.expansion = ('初級', 'Aシリーズ', 7)
        w.list_stalls = 2
        w.list_fingerprint = ('テストデッキ',)
        self.rows = [self.row('ステップアップバトル'), self.row('エキスパンション', x=.83, y=.33),
                     self.row('テストデッキ', x=.66)]
        w.step()
        self.assertIn(w.expansion, w.exhausted_expansions)
        self.assertTrue(w.series_initialized)
        w.tap.reset_mock()
        self.rows = self.popup()
        w.step()
        w.tap.assert_called_with(.58, .84, 'Aシリーズの探索を再開')
        w.tap.reset_mock()
        w.step()
        w.tap.assert_not_called()
        w.swipe.assert_called()

    def test_a_exhausted_switches_to_b_and_stays_b_after_return(self):
        w = self.worker
        w.series_initialized = True
        w.expansion_catalog.identify = Mock(return_value=7)
        w.exhausted_expansions.add(('初級', 'Aシリーズ', 7))
        self.rows = self.popup()
        for _ in range(3):
            w.step()
        self.assertEqual(w.expansion_series, 'Bシリーズ')
        self.assertIn('Aシリーズ', w.exhausted_series)
        w.tap.assert_called_with(.22, .84, '別シリーズを探す')
        w.tap.reset_mock()
        w.expansion = ('初級', 'Bシリーズ', 7)
        w.list_fingerprint = ('テストデッキ',)
        w.list_stalls = 2
        self.rows = [self.row('ステップアップバトル'), self.row('エキスパンション', x=.83, y=.33),
                     self.row('テストデッキ', x=.66)]
        w.step()
        w.tap.reset_mock()
        self.rows = self.popup()
        w.step()
        w.tap.assert_called_with(.22, .84, 'Bシリーズの探索を再開')
        w.tap.reset_mock()
        w.step()
        self.assertEqual(w.expansion_series, 'Bシリーズ')
        self.assertIn('Aシリーズ', w.exhausted_series)
        w.tap.assert_not_called()

    def test_b_exhausted_moves_to_next_difficulty(self):
        w = self.worker
        w.series_initialized = True
        w.expansion_series = 'Bシリーズ'
        w.exhausted_series.add('Aシリーズ')
        w.expansion_catalog.identify = Mock(return_value=7)
        w.exhausted_expansions.add(('初級', 'Bシリーズ', 7))
        self.rows = self.popup()
        for _ in range(3):
            w.step()
        self.assertIn('初級', w.exhausted_difficulties)
        self.assertTrue(w.pending_dismiss)
        self.rows = [self.row('ステップアップバトル'), self.row('エキスパンション')]
        w.step()
        w.tap.assert_called_with(.5, .855, '別の難易度へ戻る')
        self.rows = [self.row('ステップアップバトル'), self.row('初級', x=.71, y=.35),
                     self.row('中級', x=.71, y=.6)]
        w.step()
        self.assertEqual(w.difficulty, '中級')
        self.assertFalse(w.series_initialized)
        self.rows = self.popup()
        w.step()
        self.assertEqual(w.expansion_series, 'Aシリーズ')
        self.assertFalse(w.exhausted_series)

    def test_all_difficulties_exhausted_stops(self):
        w = self.worker
        w.exhausted_difficulties.update(('初級', '中級', '上級', 'エキスパート'))
        self.rows = [self.row('ステップアップバトル'), self.row('エキスパート', x=.71)]
        for _ in range(3):
            w.step()
        self.assertFalse(w.running)

    def test_new_difficulty_is_discovered_even_after_four_existing_ones(self):
        w = self.worker
        w.exhausted_difficulties.update(('初級', '中級', '上級', 'エキスパート'))
        self.rows = [self.row('ステップアップバトル'),
                     self.row('エキスパート', x=.71, y=.3),
                     self.row('伝説級', x=.71, y=.6),
                     self.row('10/100', x=.8, y=.65)]
        w.step()
        self.assertTrue(w.running)
        self.assertEqual(w.difficulty, '伝説級')

    def test_new_series_is_visited_after_a_and_b(self):
        w = self.worker
        w.series_initialized = True
        w.expansion_series = 'Bシリーズ'
        w.exhausted_series.add('Aシリーズ')
        w.expansion_catalog.identify = Mock(return_value=7)
        w.exhausted_expansions.add(('初級', 'Bシリーズ', 7))
        self.rows = self.popup() + [self.row('Cシリーズ', x=.8, y=.84)]
        for _ in range(3):
            w.step()
        self.assertEqual(w.expansion_series, 'Cシリーズ')
        self.assertNotIn('初級', w.exhausted_difficulties)

    def test_ocr_failure_is_not_reported_as_completion(self):
        self.rows = [self.row('ステップアップバトル')]
        w = self.worker
        w.step()
        w.step()
        with self.assertRaisesRegex(RuntimeError, '探索完了とは判定していません'):
            w.step()
        self.assertTrue(w.running)

    def test_expansion_read_failure_does_not_switch_or_mark_exhausted(self):
        w = self.worker
        w.series_initialized = True
        self.rows = [r for r in self.popup() if '/' not in r['text']]
        w.step()
        w.step()
        with self.assertRaisesRegex(RuntimeError, '未受領なしとは判定していません'):
            w.step()
        self.assertFalse(w.exhausted_series)
        w.tap.assert_not_called()

    def test_unreadable_battle_list_is_not_marked_exhausted(self):
        w = self.worker
        w.expansion = ('初級', 'Aシリーズ', 7)
        self.rows = [self.row('ステップアップバトル'), self.row('エキスパンション')]
        w.step()
        w.step()
        with self.assertRaisesRegex(RuntimeError, '未受領なしとは判定していません'):
            w.step()
        self.assertFalse(w.exhausted_expansions)

    def test_interrupted_battle_can_resume_after_restart(self):
        self.rows = [self.row('中断されたバトルがあります', y=.4),
                     self.row('はい', x=.7, y=.6)]
        self.worker.step()
        self.worker.tap.assert_called_with(.7, .6, '中断された対戦を再開')

    def test_pack_details_can_reach_battle_menu(self):
        self.rows = [self.row('提供割合', y=.85), self.row('他の拡張パック', y=.85)]
        self.worker.step()
        self.worker.tap.assert_called_with(278 / 402, 814 / 874, 'パック詳細から下部のバトルメニューへ')

    def test_locked_device_is_prepared_before_screenshot(self):
        self.worker.device.unlock.return_value = True
        self.worker.step()
        self.worker.device.activate.assert_called_once()
        self.assertIsNone(self.worker.screen)

    def test_overlay_during_capture_discards_frame_without_tapping(self):
        self.rows = [self.row('でスタート', y=.84)]
        self.worker.device.wait_foreground.side_effect = [False, True]
        self.assertEqual(self.worker.step(), 2)
        self.worker.tap.assert_not_called()

    def test_other_app_stops_before_capture_and_tap(self):
        self.worker.device.wait_foreground.side_effect = RuntimeError('別アプリ')
        with self.assertRaisesRegex(RuntimeError, '別アプリ'):
            self.worker.step()
        self.assertIsNone(self.worker.screen)
        self.worker.tap.assert_not_called()

    def test_unwinnable_battle_prevents_successful_completion(self):
        w = self.worker
        w.unresolved_rewards.add('負けたデッキ')
        w.exhausted_difficulties.add('初級')
        self.rows = [self.row('ステップアップバトル'), self.row('初級', x=.71)]
        w.step()
        w.step()
        with self.assertRaisesRegex(RuntimeError, '全受領とは判定していません'):
            w.step()

    def restarted(self, reset=False):
        with patch.object(Worker, 'log'):
            restarted = Worker(0, 900, reset_progress=reset)
        restarted.tap = Mock()
        restarted.swipe = Mock()
        restarted.log = Mock()
        restarted.reward_color = Mock(return_value=0)
        return restarted

    def test_restart_preserves_expansion_identity_and_skips_completed_expansion(self):
        w = self.worker
        identity = w.expansion_catalog.identify(screen_with_logo('expansion-ex'), {'y': .60}, 'Bシリーズ', 30)
        w.difficulty = '中級'
        w.expansion_series = 'Bシリーズ'
        w.exhausted_expansions.add(('中級', 'Bシリーズ', identity))
        w.failed['lost battle'] = 2
        w.unresolved_rewards.add('lost battle')
        w.claimed_rewards.add('claimed battle')
        w.save_progress()
        resumed = self.restarted()
        matched = resumed.expansion_catalog.identify(screen_with_logo('expansion-ex', .72), {'y': .727}, 'Bシリーズ', 30)
        self.assertEqual(matched, identity)
        self.assertIn(('中級', 'Bシリーズ', matched), resumed.exhausted_expansions)
        self.assertEqual(resumed.failed['lost battle'], 2)
        self.assertIn('claimed battle', resumed.claimed_rewards)
        self.assertIn('lost battle', resumed.unresolved_rewards)
        self.assertEqual(resumed.resume_difficulty, '中級')
        self.assertEqual(resumed.resume_series, 'Bシリーズ')

    def test_resume_seeks_saved_difficulty_then_series(self):
        w = self.worker
        w.difficulty = '上級'
        w.expansion_series = 'Bシリーズ'
        w.save_progress()
        w = self.restarted()
        self.rows = [self.row('ステップアップバトル'), self.row('エキスパンション')]
        w.step()
        w.tap.assert_called_with(.5, .855, '保存した難易度から再開するため一覧へ戻る')
        self.rows = [self.row('ステップアップバトル'), self.row('初級', x=.7)]
        w.tap.reset_mock()
        w.step()
        w.tap.assert_not_called()
        w.swipe.assert_called()
        self.rows = [self.row('ステップアップバトル'), self.row('上級', x=.7)]
        w.step()
        self.assertEqual(w.difficulty, '上級')
        self.rows = [self.row('ステップアップバトル'), self.row('エキスパンション')]
        w.step()
        self.assertFalse(w.needs_expansion_alignment)
        self.rows = self.popup()
        w.step()
        self.assertEqual(w.expansion_series, 'Bシリーズ')

    def test_step_checkpoints_selected_battle_without_waiting_for_shutdown(self):
        w = self.worker
        w.reward_color.return_value = .1
        self.rows = [self.row('ステップアップバトル'), self.row('エキスパンション'),
                     self.row('テストデッキ', x=.66)]
        w.step()
        data = json.loads(w.progress.path.read_text())
        self.assertEqual(data['cursor']['battle'], w.selected)
        self.assertIn('テストデッキ', data['cursor']['battle'])

    def test_resumed_battle_does_not_double_count_total(self):
        w = self.worker
        w.battles = 1
        w.new_battles = 1
        w.in_battle = True
        w.selected = 'saved battle'
        w.save_progress()
        w = self.restarted()
        self.rows = [self.row('VS')]
        w.step()
        self.assertEqual(w.battles, 1)
        self.assertEqual(json.loads(w.progress.path.read_text())['total_battles'], 1)
        self.assertEqual(w.selected, 'saved battle')

    def test_new_content_remains_discoverable_after_completed_run(self):
        w = self.worker
        identity = w.expansion_catalog.identify(screen_with_logo('expansion-ex'), {'y': .60}, 'Aシリーズ', 30)
        w.exhausted_expansions.add(('初級', 'Aシリーズ', identity))
        w.exhausted_difficulties.add('初級')
        w.status = 'complete'
        w.save_progress()
        w = self.restarted()
        self.assertFalse(w.exhausted_difficulties)
        updated = w.expansion_catalog.identify(screen_with_logo('expansion-ex'), {'y': .60}, 'Aシリーズ', 35)
        self.assertNotIn(('初級', 'Aシリーズ', updated), w.exhausted_expansions)

    def test_reset_progress_removes_cursor_and_keeps_backup(self):
        self.worker.difficulty = '上級'
        self.worker.save_progress()
        w = self.restarted(reset=True)
        self.assertIsNone(w.resume_difficulty)
        self.assertFalse(w.exhausted_expansions)
        self.assertTrue(w.progress.path.with_suffix('.json.bak').exists())

    def test_resume_rechecks_earlier_difficulties_after_saved_stage_finishes(self):
        self.worker.difficulty = '上級'
        self.worker.save_progress()
        w = self.restarted()
        self.rows = [self.row('ステップアップバトル'), self.row('上級', x=.7)]
        w.step()
        w.exhausted_difficulties.add('上級')
        w.tap.reset_mock()
        w.step()
        w.swipe.assert_called_with(reverse=True)
        self.rows = [self.row('ステップアップバトル'), self.row('初級', x=.7)]
        for _ in range(3):
            w.step()
        self.assertEqual(w.difficulty, '初級')

    def test_invalid_checkpoint_does_not_get_overwritten(self):
        self.worker.save_progress()
        data = json.loads(self.worker.progress.path.read_text())
        data['catalog'] = [{'series': 'Aシリーズ', 'total': 30, 'height': 3, 'pixels': 'bad'}]
        content = json.dumps(data)
        self.worker.progress.path.write_text(content)
        with self.assertRaisesRegex(RuntimeError, '元のファイルは保持'):
            self.restarted()
        self.assertEqual(self.worker.progress.path.read_text(), content)

    def test_changed_completion_count_reopens_previously_exhausted_expansion(self):
        w = self.worker
        w.series_initialized = True
        w.expansion_catalog.identify = Mock(return_value=0)
        key = ('初級', 'Aシリーズ', 0)
        w.exhausted_expansions.add(key)
        w.exhausted_counts[key] = 2
        self.rows = self.popup()  # Now displays 3/30.
        w.step()
        self.assertNotIn(key, w.exhausted_expansions)
        self.assertEqual(w.expansion, key)
        w.tap.assert_called_once()


if __name__ == '__main__':
    unittest.main()
