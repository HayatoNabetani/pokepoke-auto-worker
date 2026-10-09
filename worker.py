#!/usr/bin/env python3
"""Run solo step-up battles using screenshot OCR and observed reward icons."""
import argparse
import json
import re
import signal
import time
import unicodedata
from pathlib import Path

import numpy as np
from PIL import Image

from iphone import request, SESSION_FILE
from observe import observe, ROOT
from exploration import ExpansionCatalog
from device import Device


def normalized(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text))


def reward_color_fraction(image):
    rgb = np.asarray(image.convert('RGB'), dtype=float)
    high, low = rgb.max(axis=2), rgb.min(axis=2)
    saturation = (high - low) / np.maximum(high, 1)
    return float(np.mean((saturation > .3) & (high > 100)))


class Worker:
    def __init__(self, limit, timeout):
        self.limit = limit
        self.timeout = timeout
        self.session = SESSION_FILE.read_text().strip()
        self.prefix = '/session/' + self.session
        self.device = Device(self.session)
        self.running = True
        self.battles = 0
        self.wins = 0
        self.rows = []
        self.screen = None
        self.in_battle = False
        self.battle_since = None
        self.unknown_since = None
        self.selected = None
        self.failed = {}
        self.list_fingerprint = None
        self.list_stalls = 0
        self.expansion = None
        self.exhausted_expansions = set()
        self.difficulty = '初級'
        self.exhausted_difficulties = set()
        self.pending_dismiss = False
        self.expansion_series = 'Aシリーズ'
        self.expansion_fingerprint = None
        self.expansion_stalls = 0
        self.exhausted_series = set()
        self.result_recorded = False
        self.reward_recorded = False
        self.series_initialized = False
        self.series_needs_selection = False
        self.expansion_catalog = ExpansionCatalog()
        self.exploration_actions = 0
        self.difficulty_fingerprint = None
        self.difficulty_stalls = 0
        self.expansion_read_failures = 0
        self.difficulty_read_failures = 0
        self.series_order = []
        self.deck_read_failures = 0
        self.unresolved_rewards = set()
        (ROOT / 'logs').mkdir(exist_ok=True)

    def log(self, event, **values):
        entry = {'time': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'event': event, **values}
        print(json.dumps(entry, ensure_ascii=False), flush=True)
        with (ROOT / 'logs' / 'events.jsonl').open('a') as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + '\n')

    def find(self, text, ymin=0, ymax=1, exact=False):
        needle = normalized(text)
        return next((r for r in self.rows if ymin <= r['y'] <= ymax and
                     (normalized(r['text']) == needle if exact else
                      needle in normalized(r['text']))), None)

    def tap(self, x, y, reason):
        self.unknown_since = None
        self.log('tap', x=round(x, 4), y=round(y, 4), reason=reason)
        # WDA uses logical points, while the screenshot is rendered at 3x on this iPhone.
        request('POST', self.prefix + '/wda/tap', {'x': x * 402, 'y': y * 874})
        time.sleep(2)

    def tap_text(self, row, reason):
        self.tap(row['x'], row['y'], reason)

    def swipe(self):
        request('POST', self.prefix + '/actions', {'actions': [{
            'type': 'pointer', 'id': 'finger', 'parameters': {'pointerType': 'touch'},
            'actions': [
                {'type': 'pointerMove', 'duration': 0, 'x': 280, 'y': 680},
                {'type': 'pointerDown', 'button': 0},
                {'type': 'pause', 'duration': 100},
                {'type': 'pointerMove', 'duration': 650, 'x': 280, 'y': 360},
                {'type': 'pointerUp', 'button': 0}]}]})
        time.sleep(2)

    def reward_color(self, row):
        # The right side of an uncleared battle contains colored reward icons.
        # Cleared battles display a pale check mark in the same area.
        width, height = self.screen.size
        top = row['y'] + row['height'] / 2 + 0.015
        bottom = min(top + 0.095, 0.805)
        if bottom <= top:
            return 0
        crop = self.screen.crop((int(width * .65), int(height * top),
                                 int(width * .95), int(height * bottom)))
        return reward_color_fraction(crop)

    def series_tabs(self):
        return sorted({normalized(r['text']) for r in self.rows
                       if r['y'] > .8 and normalized(r['text']).endswith('シリーズ')})

    def difficulty_rows(self):
        # Difficulty names are labels in the right-hand badge of each card.
        # Read the labels rather than assuming a fixed number or list of names.
        return sorted((r for r in self.rows if .62 < r['x'] < .9 and .2 < r['y'] < .85
                       and '/' not in normalized(r['text'])
                       and any(c.isalpha() for c in normalized(r['text']))),
                      key=lambda r: r['y'])

    def step(self):
        if self.device.unlock():
            self.device.activate()
            self.log('device_unlocked')
            return 3
        self.device.wait_foreground()
        live_path = ROOT / 'logs' / 'current.png'
        self.rows = observe(live_path)
        self.screen = Image.open(live_path).copy()
        self.screen.save(ROOT / 'screen.png')
        if self.screen.size != (1206, 2622):
            raise RuntimeError('この実機で確認した画面サイズと異なるため停止しました。')
        # Do not send inputs outside the target app.
        if self.device.wait_foreground():
            # An overlay appeared during capture. Read a fresh frame next time.
            return 2

        if self.find('対戦相手', ymax=.2) or self.find('VS', exact=True):
            if not self.in_battle:
                self.in_battle = True
                self.battles += 1
                self.battle_since = time.monotonic()
                self.log('battle_observed', selected=self.selected)
            if time.monotonic() - self.battle_since > self.timeout:
                raise RuntimeError('対戦が制限時間を超えました。画面を確認してください。')
            self.unknown_since = None
            return 8

        start = self.find('でスタート', ymin=.7)
        if start:
            self.tap_text(start, 'スタート')
            return 3

        if self.find('中断されたバトル'):
            resume = self.find('はい', exact=True)
            if resume:
                self.tap_text(resume, '中断された対戦を再開')
                return 3

        # Results and rewards are handled here once their observed labels are known.
        finish = self.handle_result()
        if finish is not None:
            return finish

        if self.in_battle:
            if time.monotonic() - self.battle_since > self.timeout:
                raise RuntimeError('対戦が制限時間を超えました。画面を確認してください。')
            self.unknown_since = None
            return 8

        if self.limit and not self.in_battle and self.battles >= self.limit:
            if self.find('エキスパンション') and self.find('ステップアップ'):
                self.log('battle_limit_reached')
                self.running = False
                return 0

        battle = self.find('バトル!', ymin=.65)
        if battle and self.find('バトルルール'):
            if not self.find('初回報酬', ymax=.45):
                self.log('skip_claimed_reward', selected=self.selected)
                if self.selected:
                    self.failed[self.selected] = 2
                self.tap(.5, .915, '初回報酬が表示されないため一覧へ戻る')
                return 2
            off = self.find('OFF', ymin=.85)
            on = self.find('ON', ymin=.85, exact=True)
            if off:
                self.tap_text(off, 'オートONへ切り替え')
                return 1
            if not on:
                raise RuntimeError('オートONを確認できないため、対戦を開始しませんでした。')
            if self.limit and self.battles >= self.limit:
                self.running = False
                return 0
            self.tap_text(battle, 'オート対戦開始')
            self.battles += 1
            self.in_battle = True
            self.battle_since = time.monotonic()
            self.result_recorded = False
            self.reward_recorded = False
            self.log('battle_started', count=self.battles, selected=self.selected)
            self.exploration_actions = 0
            return 8

        if self.find('エキスパンション選択'):
            tabs = self.series_tabs()
            if not tabs:
                return 3
            self.series_order = sorted(set(self.series_order) | set(tabs))
            if not self.series_initialized:
                self.series_initialized = True
                self.expansion_series = self.series_order[0]
                self.exhausted_series.clear()
                self.expansion_fingerprint = None
                self.expansion_stalls = 0
                if self.find(self.expansion_series):
                    self.tap_text(self.find(self.expansion_series), self.expansion_series + 'から未クリアを探す')
                    return 2
            if self.series_needs_selection:
                tab = self.find(self.expansion_series)
                if not tab:
                    raise RuntimeError('探索中のシリーズのタブを読めないため停止しました。')
                self.series_needs_selection = False
                self.tap_text(tab, self.expansion_series + 'の探索を再開')
                return 2
            header = self.find('エキスパンション選択')
            min_count_y = header['y'] + header.get('height', .03) / 2 + .13
            counts = [r for r in self.rows if re.fullmatch(r'\d+/\d+', normalized(r['text']))
                      and .38 < r['x'] < .6 and min_count_y < r['y'] < .81]
            if not counts and not self.find('ありません', ymin=.2, ymax=.8):
                self.expansion_read_failures += 1
                if self.expansion_read_failures >= 3:
                    raise RuntimeError('エキスパンション一覧の件数を読めないため停止しました。未受領なしとは判定していません。')
                return 3
            self.expansion_read_failures = 0
            visible_keys = []
            for row in sorted(counts, key=lambda r: r['y']):
                done, total = map(int, normalized(row['text']).split('/'))
                identity = self.expansion_catalog.identify(self.screen, row, self.expansion_series, total)
                key = (self.difficulty, self.expansion_series, identity)
                visible_keys.append(key)
                if done < total and key not in self.exhausted_expansions:
                    self.expansion = key
                    self.tap(.5, row['y'] - .07, '未クリアを含むエキスパンション')
                    self.list_fingerprint = None
                    self.list_stalls = 0
                    self.expansion_stalls = 0
                    self.log('expansion_selected', difficulty=self.difficulty,
                             series=self.expansion_series, identity=identity)
                    return 2
            fingerprint = tuple(visible_keys)
            self.expansion_stalls = self.expansion_stalls + 1 if fingerprint == self.expansion_fingerprint else 0
            self.expansion_fingerprint = fingerprint
            if self.expansion_stalls >= 2:
                self.exhausted_series.add(self.expansion_series)
                other = next((name for name in self.series_order if name not in self.exhausted_series), None)
                if other and self.find(other):
                    self.tap_text(self.find(other), '別シリーズを探す')
                    self.expansion_series = other
                    self.expansion_stalls = 0
                    self.expansion_fingerprint = None
                    self.log('series_changed', difficulty=self.difficulty, series=other)
                elif other:
                    raise RuntimeError('未探索シリーズのタブを読めないため停止しました。')
                else:
                    self.exhausted_difficulties.add(self.difficulty)
                    self.pending_dismiss = True
                    self.series_initialized = False
                    self.log('difficulty_exhausted', difficulty=self.difficulty)
                    self.tap(.5, .915, 'エキスパンション選択を閉じる')
            else:
                self.swipe()
            return 2

        if self.find('ステップアップ') and self.find('エキスパンション'):
            if self.pending_dismiss:
                self.pending_dismiss = False
                self.exhausted_series.clear()
                self.tap(.5, .855, '別の難易度へ戻る')
                return 2
            decks = [r for r in self.rows if 'デッキ' in normalized(r['text'])
                     and r['x'] > .35 and .36 < r['y'] < .72]
            if not decks:
                self.deck_read_failures += 1
                if self.deck_read_failures >= 3:
                    raise RuntimeError('バトル一覧を読めないため停止しました。未受領なしとは判定していません。')
                return 3
            self.deck_read_failures = 0
            for row in sorted(decks, key=lambda r: r['y']):
                score = self.reward_color(row)
                key = str((self.difficulty, self.expansion, normalized(row['text'])))
                if score > .035 and self.failed.get(key, 0) < 2:
                    self.selected = key
                    self.log('unclaimed_reward_candidate', deck=row['text'], color_score=score)
                    self.tap_text(row, '初回報酬アイコンが残るバトル')
                    return 2
            fingerprint = tuple(normalized(r['text']) for r in decks)
            self.list_stalls = self.list_stalls + 1 if fingerprint == self.list_fingerprint else 0
            self.list_fingerprint = fingerprint
            if self.list_stalls >= 2:
                if self.expansion:
                    self.exhausted_expansions.add(self.expansion)
                    self.log('expansion_exhausted', expansion=self.expansion)
                row = self.find('エキスパンション')
                self.series_needs_selection = self.series_initialized
                self.tap_text(row, '別エキスパンションを探す')
                self.list_stalls = 0
            else:
                self.swipe()
            return 2

        if self.find('ひとりで') and self.find('ステップアップ', ymin=.55):
            self.tap_text(self.find('ステップアップ', ymin=.55), 'ステップアップバトルへ')
            return 2

        if self.find('ステップアップ'):
            visible = []
            rows = self.difficulty_rows()
            if not rows:
                self.difficulty_read_failures += 1
                if self.difficulty_read_failures >= 3:
                    raise RuntimeError('難易度一覧を読めないため停止しました。探索完了とは判定していません。')
                return 3
            self.difficulty_read_failures = 0
            for row in rows:
                difficulty = normalized(row['text'])
                visible.append(difficulty)
                if difficulty not in self.exhausted_difficulties:
                    self.difficulty = difficulty
                    self.series_initialized = False
                    self.series_needs_selection = False
                    self.expansion = None
                    self.exploration_actions = 0
                    self.difficulty_stalls = 0
                    self.difficulty_fingerprint = None
                    self.series_order = []
                    self.log('difficulty_selected', difficulty=difficulty)
                    self.tap_text(row, '難易度を選択')
                    return 2
            fingerprint = tuple(visible)
            self.difficulty_stalls = self.difficulty_stalls + 1 if fingerprint == self.difficulty_fingerprint else 0
            self.difficulty_fingerprint = fingerprint
            if visible and self.difficulty_stalls >= 2:
                if self.unresolved_rewards:
                    raise RuntimeError('再挑戦しても勝てないバトルが残っています。報酬の全受領とは判定していません。')
                self.log('no_unclaimed_battles_found')
                self.running = False
                return 0
            self.swipe()
            return 2

        solo = self.find('ひとりで', ymin=.55)
        stepup = self.find('ステップアップ', ymin=.55)
        if stepup:
            self.tap_text(stepup, 'ステップアップバトルへ')
            return 2
        if solo:
            self.tap_text(solo, 'ひとりでバトルへ')
            return 2
        if self.find('ゲットチャレンジ') and self.find('ショップ'):
            self.tap(278 / 402, 814 / 874, '下部のバトルメニュー')
            return 2
        if self.find('提供割合', ymin=.8) and self.find('他の拡張パック', ymin=.8):
            self.tap(278 / 402, 814 / 874, 'パック詳細から下部のバトルメニューへ')
            return 2

        if self.unknown_since is None:
            self.unknown_since = time.monotonic()
            self.log('waiting_for_known_screen', text=[r['text'] for r in self.rows])
        elif time.monotonic() - self.unknown_since > 60:
            raise RuntimeError('未対応の画面が60秒続いたため停止しました。screen.pngを確認してください。')
        return 5

    def handle_result(self):
        advance = self.find('タップですすむ', ymin=.85)
        victory = self.find('勝利', ymax=.35)
        defeat = self.find('敗北', ymax=.35)
        if advance and (victory or defeat or self.result_recorded):
            if not self.result_recorded:
                self.result_recorded = True
                self.in_battle = False
                if victory:
                    self.wins += 1
                elif self.selected:
                    self.failed[self.selected] = self.failed.get(self.selected, 0) + 1
                    if self.failed[self.selected] >= 2:
                        self.unresolved_rewards.add(self.selected)
                self.log('battle_result', outcome='win' if victory else 'loss', selected=self.selected)
            self.tap_text(advance, '対戦結果の続きへ')
            return 2
        next_button = self.find('次へ', ymin=.8, exact=True)
        if next_button and self.find('プレイヤー経験値'):
            self.in_battle = False
            if self.find('初回報酬') and not self.reward_recorded:
                self.reward_recorded = True
                self.unresolved_rewards.discard(self.selected)
                self.log('first_reward_received', selected=self.selected)
                self.screen.save(ROOT / 'logs' / f'reward-{self.battles}.png')
            self.tap_text(next_button, '報酬を受け取って一覧へ')
            self.list_fingerprint = None
            self.list_stalls = 0
            return 3
        if self.find('新たなバトルがオープン'):
            ok = self.find('OK', ymin=.5, exact=True)
            if ok:
                self.tap_text(ok, '新しいバトル解放のお知らせを閉じる')
                return 2
        return None

    def run(self):
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, 'running', False))
        self.log('worker_started', limit=self.limit)
        try:
            while self.running:
                if not self.in_battle and self.exploration_actions >= 200:
                    raise RuntimeError('探索が進まないため停止しました。ログとscreen.pngを確認してください。')
                if not self.in_battle:
                    self.exploration_actions += 1
                time.sleep(self.step())
        except KeyboardInterrupt:
            self.log('stopped_by_user')
        except Exception as error:
            self.log('stopped_on_error', error=str(error))
            raise
        finally:
            self.log('worker_finished', battles=self.battles, wins=self.wins)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--max-battles', type=int, default=0,
                        help='0: 未受領のバトルがなくなるまで継続')
    parser.add_argument('--battle-timeout', type=int, default=900)
    args = parser.parse_args()
    if args.max_battles < 0 or args.battle_timeout < 1:
        parser.error('max-battles must be nonnegative; battle-timeout must be positive')
    Worker(args.max_battles, args.battle_timeout).run()
