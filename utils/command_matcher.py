import difflib

class CommandMatcher:
    def __init__(self):
        # Define command variations and emoji mappings
        self.command_variations = {
            'menu': ['menu', 'memu', 'menus', 'men', 'mneu', 'mnu'],
            'yes': ['yes', 'y', 'ye', 'yse', 'ys', '👍', 'ok', 'okay', 'affirmative'],
            'no': ['no', 'n', 'nope', 'nah', '❌', 'cancel', 'not'],
            'help': ['help', 'hlep', 'halp', 'hep', 'assist', 'support', '?'],
            'confirm': ['confirm', 'cnofirm', 'confrim', '👍', 'ok', 'accept'],
            'cancel': ['cancel', 'canel', 'cnacel', '❌', 'stop', 'abort', 'no'],
        }
        self.emoji_map = {
            '👍': 'yes',
            '❌': 'no',
        }

    def match(self, user_input):
        user_input = user_input.strip().lower()
        # Emoji direct mapping
        if user_input in self.emoji_map:
            return {
                'command': self.emoji_map[user_input],
                'confidence': 1.0,
                'correction': f"Interpreted emoji '{user_input}' as '{self.emoji_map[user_input]}'"
            }
        # Find best match
        best_command = None
        best_score = 0.0
        best_variant = None
        for command, variants in self.command_variations.items():
            for variant in variants:
                score = difflib.SequenceMatcher(None, user_input, variant).ratio()
                if score > best_score:
                    best_score = score
                    best_command = command
                    best_variant = variant
        # Set a reasonable threshold for confidence
        if best_score > 0.75:
            correction = None
            if user_input != best_variant:
                correction = f"Did you mean '{best_variant}' ({best_command})?"
            return {
                'command': best_command,
                'confidence': best_score,
                'correction': correction
            }
        return {
            'command': None,
            'confidence': best_score,
            'correction': 'No close command match found.'
        }
