"""Recognize expansion logos despite small OCR/scroll position differences."""
import base64

import numpy as np


class ExpansionCatalog:
    def __init__(self):
        self.entries = []

    def export(self):
        return [{'series': entry['series'], 'total': entry['total'],
                 'height': entry['template'].shape[0],
                 'pixels': base64.b64encode(entry['template'].astype(np.uint8).tobytes()).decode('ascii')}
                for entry in self.entries]

    def restore(self, entries):
        restored = []
        for entry in entries:
            if (not isinstance(entry['series'], str) or not isinstance(entry['total'], int)
                    or entry['total'] < 1 or not isinstance(entry['height'], int)
                    or not 1 <= entry['height'] <= 200):
                raise ValueError('Invalid expansion catalog')
            pixels = base64.b64decode(entry['pixels'], validate=True)
            template = np.frombuffer(pixels, dtype=np.uint8).reshape(entry['height'], 120).astype(float)
            restored.append({'series': entry['series'], 'total': entry['total'], 'template': template})
        self.entries = restored

    @staticmethod
    def crop(screen, row, padding=0):
        width, height = screen.size
        box = (int(width * .14), int(height * (row['y'] - .115 - padding)),
               int(width * .45), int(height * (row['y'] - .035 + padding)))
        image = screen.crop(box).convert('L')
        return np.asarray(image.resize((120, round(image.height * 120 / image.width))), dtype=float)

    @staticmethod
    def similarity(search, template):
        if search.shape[0] < template.shape[0]:
            return 0
        centered = template - template.mean()
        norm = np.linalg.norm(centered)
        if norm < 1:
            return 0
        scores = []
        for top in range(search.shape[0] - template.shape[0] + 1):
            window = search[top:top + template.shape[0]]
            window = window - window.mean()
            scores.append(float(np.sum(window * centered) /
                                max(np.linalg.norm(window) * norm, 1)))
        return max(scores, default=0)

    def identify(self, screen, row, series, total):
        search = self.crop(screen, row, padding=.025)
        matches = [(self.similarity(search, entry['template']), index)
                   for index, entry in enumerate(self.entries)
                   if entry['series'] == series and entry['total'] == total]
        score, index = max(matches, default=(0, -1))
        if score >= .90:
            return index
        self.entries.append({'series': series, 'total': total,
                             'template': self.crop(screen, row)})
        return len(self.entries) - 1
