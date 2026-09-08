from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
from werkzeug.utils import secure_filename
import base64
from PIL import Image
import io
import requests
import json

app = Flask(__name__)
CORS(app)

# Configuration
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'doc', 'docx', 'txt', 'md'}
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# OpenExecutive API Configuration
OPENEXECUTIVE_API_URL = os.environ.get('OPENEXECUTIVE_API_URL', 'http://localhost:8000')
OPENEXECUTIVE_API_KEY = os.environ.get('OPENEXECUTIVE_API_KEY', '')  # x-api-key header

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

@app.route('/api/chat', methods=['POST'])
def chat():
    """Handle chat requests using OpenExecutive API"""
    try:
        data = request.json
        message = data.get('message', '')
        
        if not OPENEXECUTIVE_API_URL:
            # Fallback to simulated response if OpenExecutive not configured
            response = f"I received your message: '{message}'. To enable real AI responses, set OPENEXECUTIVE_API_URL environment variable."
            return jsonify({'response': response})
        
        # Call OpenExecutive chat endpoint
        headers = {}
        if OPENEXECUTIVE_API_KEY:
            headers['x-api-key'] = OPENEXECUTIVE_API_KEY
        
        payload = {
            'message': message,
            'stream': False  # Use non-streaming for simplicity
        }
        
        response = requests.post(
            f'{OPENEXECUTIVE_API_URL}/chat',
            json=payload,
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 200:
            # OpenExecutive returns SSE streaming format
            # Parse the SSE response to extract the actual content
            response_text = response.text
            lines = response_text.split('\n')
            
            # Extract content from SSE data lines
            content_parts = []
            for line in lines:
                if line.startswith('data: '):
                    try:
                        data_json = json.loads(line[6:])
                        # Check if this is a content message (not debug/error/done)
                        if data_json.get('type') == 'content':
                            content_parts.append(data_json.get('content', ''))
                        elif data_json.get('type') == 'error':
                            return jsonify({'response': f"OpenExecutive error: {data_json.get('message', 'Unknown error')}"})
                    except:
                        pass
            
            if content_parts:
                return jsonify({'response': ''.join(content_parts)})
            else:
                # If no content found, return demo response
                return jsonify({'response': f"I received your message: '{message}'. OpenExecutive is running but requires a valid ANTHROPIC_API_KEY for real AI responses."})
        else:
            return jsonify({'response': f"Error from OpenExecutive API: {response.status_code} - {response.text}"})
            
    except requests.exceptions.ConnectionError:
        return jsonify({'response': f"Could not connect to OpenExecutive at {OPENEXECUTIVE_API_URL}. Make sure it's running."})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/vision', methods=['POST'])
def vision():
    """Handle image analysis requests"""
    try:
        if 'image' not in request.files:
            return jsonify({'error': 'No image file provided'}), 400
        
        file = request.files['image']
        
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({'error': 'Invalid file type'}), 400
        
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        # For demo purposes, return a simulated analysis
        # In production, integrate with GPT-4 Vision or similar
        analysis = f"""Image Analysis Results:
- File: {filename}
- Size: {os.path.getsize(filepath)} bytes
- Format: {filename.rsplit('.', 1)[1].upper()}

This is a simulated analysis. To enable real AI vision capabilities:
1. Set OPENAI_API_KEY environment variable
2. The system will use GPT-4 Vision API
3. Image will be analyzed for content, objects, text, and context"""
        
        return jsonify({'analysis': analysis})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/code', methods=['POST'])
def code():
    """Handle code generation requests"""
    try:
        data = request.json
        prompt = data.get('prompt', '')
        language = data.get('language', 'python')
        
        # For demo purposes, return a simulated code generation
        # In production, integrate with OpenAI Codex or similar
        code = f"""# Generated code for: {prompt}
# Language: {language}

# This is a simulated code generation.
# To enable real AI code generation:
# 1. Set OPENAI_API_KEY environment variable
# 2. The system will use GPT-4 or Codex API
# 3. Code will be generated based on your prompt

def example_function():
    \"\"\"
    Example function placeholder.
    Replace with actual generated code.
    \"\"\"
    pass

if __name__ == "__main__":
    example_function()"""
        
        return jsonify({'code': code})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/docs', methods=['POST'])
def docs():
    """Handle document analysis using OpenExecutive API"""
    try:
        if 'document' not in request.files:
            return jsonify({'error': 'No document file provided'}), 400
        
        file = request.files['document']
        
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({'error': 'Invalid file type'}), 400
        
        if not OPENEXECUTIVE_API_URL:
            # Fallback to local analysis if OpenExecutive not configured
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            
            content = ''
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
            except:
                content = '[Binary file - content not readable]'
            
            analysis = f"""Document Analysis Results (Local):
- File: {filename}
- Size: {os.path.getsize(filepath)} bytes
- Content length: {len(content)} characters

Content Preview:
{content[:500]}{'...' if len(content) > 500 else ''}

To enable AI-powered analysis via OpenExecutive, set OPENEXECUTIVE_API_URL environment variable."""
            
            return jsonify({'analysis': analysis})
        
        # Forward document to OpenExecutive
        headers = {}
        if OPENEXECUTIVE_API_KEY:
            headers['x-api-key'] = OPENEXECUTIVE_API_KEY
        
        files = {'file': (file.filename, file.stream, file.content_type)}
        
        response = requests.post(
            f'{OPENEXECUTIVE_API_URL}/documents',
            files=files,
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 200:
            try:
                result = response.json()
                return jsonify({'analysis': result.get('message', 'Document uploaded successfully to OpenExecutive')})
            except:
                return jsonify({'analysis': f"Document uploaded to OpenExecutive. Response: {response.text}"})
        else:
            return jsonify({'analysis': f"Error from OpenExecutive API: {response.status_code} - {response.text}"})
            
    except requests.exceptions.ConnectionError:
        return jsonify({'analysis': f"Could not connect to OpenExecutive at {OPENEXECUTIVE_API_URL}. Make sure it's running."})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/')
def index():
    """Serve the frontend HTML file"""
    return send_from_directory('..', 'index.html')

@app.route('/styles.css')
def styles():
    """Serve the CSS file"""
    return send_from_directory('..', 'styles.css')

@app.route('/app.js')
def app_js():
    """Serve the JavaScript file"""
    return send_from_directory('..', 'app.js')

@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'openexecutive_configured': bool(OPENEXECUTIVE_API_URL),
        'openexecutive_url': OPENEXECUTIVE_API_URL
    })

if __name__ == '__main__':
    app.run(debug=True, port=5000)
