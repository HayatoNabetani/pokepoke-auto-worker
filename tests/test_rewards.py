import unittest
from pathlib import Path
from PIL import Image
from worker import reward_color_fraction, normalized, Worker

FIXTURES = Path(__file__).parent / 'fixtures'


class RewardRecognitionTests(unittest.TestCase):
    def test_claimed_battle_with_remaining_challenge_is_not_selected(self):
        # Captured after receiving the initial reward: battle challenges remain 1/2.
        with Image.open(FIXTURES / 'claimed.png') as image:
            self.assertLess(reward_color_fraction(image), .035)

    def test_unclaimed_battle_is_selected(self):
        # Captured newly unlocked battle with its three initial reward icons.
        with Image.open(FIXTURES / 'unclaimed.png') as image:
            self.assertGreater(reward_color_fraction(image), .035)

    def test_full_width_battle_button(self):
        self.assertEqual(normalized('バトル！'), 'バトル!')

    def test_result_pages_count_one_win(self):
        worker = Worker.__new__(Worker)
        worker.rows = [
            {'text': '勝利！', 'x': .5, 'y': .26},
            {'text': 'タップですすむ', 'x': .5, 'y': .906},
        ]
        worker.result_recorded = False
        worker.in_battle = True
        worker.wins = 0
        worker.selected = 'test'
        worker.log = lambda *args, **kwargs: None
        worker.tap_text = lambda *args: None
        worker.handle_result()
        worker.handle_result()
        self.assertEqual(worker.wins, 1)
        self.assertFalse(worker.in_battle)


if __name__ == '__main__':
    unittest.main()
