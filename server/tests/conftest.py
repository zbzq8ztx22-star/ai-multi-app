import os

# Set test-safe config before app.py is imported so create_app() picks it up.
os.environ["OPENEXECUTIVE_API_URL"] = "http://openexec.test"
os.environ["OPENEXECUTIVE_API_KEY"] = "test-key"
os.environ["FLASK_DEBUG"] = "0"
os.environ["CORS_ORIGINS"] = "*"
