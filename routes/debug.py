import os
from flask import Blueprint, jsonify, request, abort
from services.enhanced_user_profile_manager import EnhancedUserProfileManager
from utils.command_matcher import CommandMatcher
from services.onboarding_manager import OnboardingManager
from utils.logging import log_structured
import time

def is_dev():
    return os.getenv('FLASK_ENV', 'production') == 'development'

debug_bp = Blueprint('debug', __name__)

# Assume redis_client is available globally or injected
from services.redis_service import redis_client
profile_manager = EnhancedUserProfileManager(redis_client)
command_matcher = CommandMatcher()
onboarding_manager = OnboardingManager(redis_client)

@debug_bp.before_request
def restrict_debug():
    if not is_dev():
        abort(403)

@debug_bp.route('/test-user-profile/<phone>')
def test_user_profile(phone):
    profile = profile_manager.get_profile(phone)
    return jsonify(profile)

@debug_bp.route('/test-fuzzy-match/<command>')
def test_fuzzy_match(command):
    result = command_matcher.match(command)
    return jsonify(result)

@debug_bp.route('/test-onboarding-state/<phone>')
def test_onboarding_state(phone):
    state = onboarding_manager.get_onboarding_state(phone)
    complete = onboarding_manager.is_onboarding_complete(phone)
    return jsonify({'state': state, 'complete': complete})

@debug_bp.route('/simulate-user-journey/<scenario>')
def simulate_user_journey(scenario):
    # Example scenarios: 'new_user', 'returning_user', 'fuzzy_match', 'error_handling'
    results = []
    if scenario == 'new_user':
        phone = 'test123'
        responses = ['Hi', "I'm Alice", "I have Ben who's 7", 'alice@example.com']
        results = simulate_onboarding_conversation(phone, responses)
    elif scenario == 'returning_user':
        phone = 'test456'
        profile_manager.update_profile(phone, {'name': 'Bob', 'onboarding_complete': True})
        results = [profile_manager.get_profile(phone)]
    elif scenario == 'fuzzy_match':
        test_cases = ['ad expnse', 'add trip', 'remind me', 'set calndar']
        results = test_fuzzy_matching_accuracy(test_cases)
    elif scenario == 'error_handling':
        phone = 'test789'
        results = [profile_manager.get_profile(phone), onboarding_manager.get_onboarding_state(phone)]
    else:
        results = ['Unknown scenario']
    return jsonify(results)

@debug_bp.route('/validate-user-data/<phone>')
def validate_user_data(phone):
    profile = profile_manager.get_profile(phone)
    valid = validate_profile_data_integrity(profile)
    return jsonify({'valid': valid, 'profile': profile})

# --- Testing Utilities ---
def create_test_user_profile(phone, name, children, email):
    profile = {'name': name, 'family_members': children, 'email': email, 'onboarding_complete': True}
    profile_manager.update_profile(phone, profile)
    return profile

def simulate_onboarding_conversation(phone, responses):
    outputs = []
    for msg in responses:
        state = onboarding_manager.get_onboarding_state(phone)
        if state == onboarding_manager.WELCOME:
            onboarding_manager.advance_onboarding_state(phone, {})
            outputs.append(onboarding_manager.generate_onboarding_prompt(state, {}))
        elif state == onboarding_manager.NAME_COLLECTION:
            name = onboarding_manager.extract_name_from_natural_language(msg)
            onboarding_manager.advance_onboarding_state(phone, {'name': name})
            outputs.append(f"Name set: {name}")
        elif state == onboarding_manager.FAMILY_INFO:
            fam = onboarding_manager.extract_family_members(msg)
            onboarding_manager.advance_onboarding_state(phone, {'family_members': fam})
            outputs.append(f"Family set: {fam}")
        elif state == onboarding_manager.EMAIL_SETUP:
            onboarding_manager.advance_onboarding_state(phone, {'email': msg})
            outputs.append(f"Email set: {msg}")
        elif state == onboarding_manager.COMPLETION:
            outputs.append('Onboarding complete!')
            break
    return outputs

def test_fuzzy_matching_accuracy(test_cases):
    results = {}
    for case in test_cases:
        results[case] = command_matcher.match(case)
    return results

def validate_profile_data_integrity(profile):
    # Simple checks for required fields
    if not profile.get('name') or not profile.get('onboarding_complete'):
        return False
    if 'family_members' in profile and not isinstance(profile['family_members'], list):
        return False
    return True

def benchmark_profile_operations():
    start = time.time()
    for i in range(100):
        phone = f'test{i}'
        profile_manager.get_profile(phone)
    duration = time.time() - start
    return {'operations': 100, 'duration_sec': duration}
