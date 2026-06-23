import os

class Config(object):
    """Base configuration shared across environments."""
    # Always load your secret key securely from an environment variable
    SECRET_KEY = os.environ.get('SECRET_KEY', 'default-fallback-key-change-this')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    POLL_INTERVAL = int(os.environ.get('POLL_INTERVAL', 10))  # seconds

class DevelopmentConfig(Config):
    """Local development configuration."""
    DEBUG = True  # Enables the interactive debugger and auto-reloader
    TESTING = False
    SQLALCHEMY_DATABASE_URI = os.environ.get('DEV_DATABASE_URL', 'sqlite:///dev.db')
    EXPRESS_URL = os.environ.get('DEV_EXPRESS_URL')  # Local Express server for development

class ProductionConfig(Config):
    """Live production configuration."""
    DEBUG = False
    TESTING = False
    # Enforce strict cookie security settings for production HTTPS
    SESSION_COOKIE_SECURE = True
    REMOTE_ADDR_X_FORWARDED_FOR = True  # Required if using a reverse proxy like Nginx
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')  # Absolute must from env
    EXPRESS_URL = os.environ.get('EXPRESS_URL')
