import logging
from typing import Optional, Dict, Any
from werkzeug.security import generate_password_hash, check_password_hash

logger = logging.getLogger(__name__)

class AuthService:
    def __init__(self):
        self.users = {
            'broker1': {
                'username': 'broker1',
                'password_hash': generate_password_hash('broker123'),
                'role': 'broker',
                'name': 'John Broker'
            },
            'broker2': {
                'username': 'broker2',
                'password_hash': generate_password_hash('broker123'),
                'role': 'broker',
                'name': 'Jane Broker'
            },
            'assessor1': {
                'username': 'assessor1',
                'password_hash': generate_password_hash('assessor123'),
                'role': 'assessor',
                'name': 'Michael Assessor'
            },
            'assessor2': {
                'username': 'assessor2',
                'password_hash': generate_password_hash('assessor123'),
                'role': 'assessor',
                'name': 'Sarah Assessor'
            },
            'demo': {
                'username': 'demo',
                'password_hash': generate_password_hash('demo'),
                'role': 'broker',
                'name': 'Demo User'
            }
        }
        logger.info(f"Auth service initialized with {len(self.users)} users")
    
    def authenticate(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        if not username or not password:
            return None
        
        user = self.users.get(username)
        if not user:
            logger.warning(f"Authentication failed: User '{username}' not found")
            return None
        
        if check_password_hash(user['password_hash'], password):
            logger.info(f"User '{username}' authenticated successfully")
            return {
                'username': user['username'],
                'role': user['role'],
                'name': user['name'],
                'user_id': f"{user['role']}_{user['username']}"
            }
        
        logger.warning(f"Authentication failed: Invalid password for user '{username}'")
        return None
    
    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        user = self.users.get(username)
        if user:
            return {
                'username': user['username'],
                'role': user['role'],
                'name': user['name'],
                'user_id': f"{user['role']}_{user['username']}"
            }
        return None
    
    def add_user(self, username: str, password: str, role: str, name: str) -> bool:
        if username in self.users:
            logger.warning(f"Cannot add user: '{username}' already exists")
            return False
        
        if role not in ['broker', 'assessor']:
            logger.warning(f"Cannot add user: Invalid role '{role}'")
            return False
        
        self.users[username] = {
            'username': username,
            'password_hash': generate_password_hash(password),
            'role': role,
            'name': name
        }
        
        logger.info(f"User '{username}' created successfully with role '{role}'")
        return True
    
    def get_demo_credentials(self) -> Dict[str, str]:
        return {
            'broker': {
                'username': 'broker1',
                'password': 'broker123',
                'role': 'broker'
            },
            'assessor': {
                'username': 'assessor1',
                'password': 'assessor123',
                'role': 'assessor'
            },
            'demo': {
                'username': 'demo',
                'password': 'demo',
                'role': 'broker'
            }
        }
