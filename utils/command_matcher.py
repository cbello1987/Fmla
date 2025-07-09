import difflib

class CommandMatcher:
    def __init__(self):
        # Expanded command variations for family/parent context
        self.command_variations = {
            # Navigation
            'menu': ['menu', 'memu', 'menus', 'men', 'mneu', 'mnu', '📅', 'main menu', 'back to menu', 'back'],
            'help': ['help', 'hlep', 'halp', 'hep', 'assist', 'support', '?', 'info', 'information'],
            'settings': ['settings', 'setting', 'setings', 'seting', '⚙️', 'configure', 'config', 'preferences', 'prefs', 'set up', 'setup', 'setpu', 'setp', 'set-up'],
            'back': ['back', 'bak', 'bck', 'return', 'go back', 'previous'],
            # Confirmation
            'yes': ['yes', 'y', 'ye', 'yse', 'ys', '👍', 'ok', 'okay', 'affirmative', 'yep', 'correct', 'right', 'sure', 'yah', 'ya', 'yup', 'of course', 'alright', 'all right', 'confirm', 'done', 'go'],
            'confirm': ['confirm', 'cnofirm', 'confrim', '👍', 'ok', 'accept', 'done', 'correct', 'right'],
            # Rejection
            'no': ['no', 'n', 'nope', 'nah', '❌', 'cancel', 'not', 'wrong', 'stop', 'abort', 'never', 'no way', 'incorrect', 'remove', 'clear', 'reset'],
            'cancel': ['cancel', 'canel', 'cnacel', '❌', 'stop', 'abort', 'no', 'remove', 'clear', 'reset'],
            'wrong': ['wrong', 'not right', 'incorrect', 'nope', '❌'],
            # Setup/Data
            'setup': ['setup', 'set up', 'setpu', 'configure', 'config', 'set-up', 'settings', '⚙️'],
            'delete': ['delete', 'remove', 'clear', 'reset', 'erase', 'start over', 'wipe'],
        }
        self.emoji_map = {
            '👍': 'yes',
            '❌': 'no',
            '📅': 'menu',
            '⚙️': 'settings',
        }
        # Confirmation and rejection patterns for helper functions
        self.confirmation_patterns = set(self.command_variations['yes'] + self.command_variations['confirm'])
        self.rejection_patterns = set(self.command_variations['no'] + self.command_variations['cancel'] + self.command_variations['wrong'])

    def match(self, user_input):
        original_input = user_input
        user_input = user_input.strip().lower()
        # Emoji direct mapping
        if user_input in self.emoji_map:
            return {
                'original_input': original_input,
                'command': self.emoji_map[user_input],
                'confidence': 1.0,
                'correction': f"I think you meant '{self.emoji_map[user_input].capitalize()}'!"
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
        if best_score > 0.72:
            correction = None
            if user_input != best_variant:
                correction = f"I think you meant '{best_command.capitalize()}'!"
            return {
                'original_input': original_input,
                'command': best_command,
                'confidence': best_score,
                'correction': correction
            }
        return {
            'original_input': original_input,
            'command': None,
            'confidence': best_score,
            'correction': 'No close command match found.'
        }

    def is_confirmation(self, text):
        text = text.strip().lower()
        # Emoji direct mapping
        if text in self.emoji_map and self.emoji_map[text] == 'yes':
            return True
        for pattern in self.confirmation_patterns:
            if difflib.SequenceMatcher(None, text, pattern).ratio() > 0.8:
                return True
        return False

    def is_rejection(self, text):
        text = text.strip().lower()
        # Emoji direct mapping
        if text in self.emoji_map and self.emoji_map[text] == 'no':
            return True
        for pattern in self.rejection_patterns:
            if difflib.SequenceMatcher(None, text, pattern).ratio() > 0.8:
                return True
        return False
