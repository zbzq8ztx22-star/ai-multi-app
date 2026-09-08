# AI Multi-App

A comprehensive multi-purpose AI application with chat, vision, code generation, and document analysis capabilities, powered by OpenExecutive API.

## Features

- **AI Chat**: Conversational AI interface powered by OpenExecutive's advanced AI agents
- **Vision**: Image analysis and understanding using AI vision models
- **Code Generation**: Generate code in multiple programming languages based on natural language descriptions
- **Document Analysis**: Upload and analyze documents for insights and summaries

## Tech Stack

### Frontend
- Vanilla HTML5
- CSS3
- JavaScript (ES6+)
- No build tools required

### Backend
- Flask (Python)
- Flask-CORS
- Pillow (image processing)
- Requests (HTTP client)
- **OpenExecutive API** - Advanced AI executive system with multiple specialist agents

## Quick Start (Windows)

### Automated Installation

Run the installation script:

```powershell
.\install.ps1
```

This will:
- Install Python dependencies
- Set up OpenExecutive with all required libraries
- Create configuration files
- Install timezone libraries

### Manual Installation

#### Prerequisites
- Python 3.11+ (download from https://www.python.org/)
- PowerShell (included with Windows)

#### Step 1: Install Dependencies

```powershell
# Install uv package manager
python -m pip install uv

# Install AI Multi-App dependencies
cd server
python -m pip install -r requirements.txt
cd ..

# Install OpenExecutive dependencies
cd OpenExecutive\packages\core
python -m uv sync
.venv\Scripts\python.exe -m pip install pytz tzdata
cd ..\..\..
```

#### Step 2: Configure OpenExecutive

Create `OpenExecutive\.env`:
```
ANTHROPIC_API_KEY=sk-ant-your-key-here
EXEC_EMAIL_ADDRESS=exec@example.com
```

Get your Anthropic API key from: https://console.anthropic.com/

#### Step 3: Configure AI Multi-App

Create `server\.env`:
```
OPENEXECUTIVE_API_URL=http://localhost:8000
OPENEXECUTIVE_API_KEY=
```

## Running the Application

### Start OpenExecutive (Required for AI features)

Open a terminal and run:

```powershell
cd OpenExecutive\packages\core
.venv\Scripts\python.exe -m uvicorn openexecutive.api.main:app --reload --port 8000
```

OpenExecutive will run on `http://localhost:8000`

### Start AI Multi-App

Open a new terminal and run:

```powershell
cd server
python app.py
```

The application will run on `http://localhost:5000`

Open your browser and navigate to: http://localhost:5000

## Usage

### Chat
- Navigate to the Chat tab
- Type your message and press Enter or click Send
- The AI will respond using OpenExecutive's advanced AI agents

### Vision
- Navigate to the Vision tab
- Upload an image by dragging and dropping or clicking to browse
- Click "Analyze Image" to get AI-powered analysis

### Code Generation
- Navigate to the Code tab
- Select your programming language
- Describe the code you need
- Click "Generate Code" to get the generated code

### Document Analysis
- Navigate to the Documents tab
- Upload a document (PDF, DOC, DOCX, TXT, MD)
- Click "Analyze Document" to get insights

## Architecture

### OpenExecutive Integration

The application integrates with OpenExecutive, a complex AI executive system featuring:

- **Multiple Specialist Agents**: Different AI agents for various tasks
- **Episodic Memory**: Context-aware conversation history
- **Knowledge Base**: Built-in knowledge chunks (194 included)
- **Skills System**: 15 built-in skills for various tasks
- **ChromaDB**: Vector store for knowledge retrieval
- **Anthropic Claude Models**: Advanced language models

### API Flow

```
User → AI Multi-App (Flask) → OpenExecutive API → Anthropic Claude
```

## API Endpoints

### POST /api/chat
Handle chat requests using OpenExecutive API

### POST /api/vision
Handle image analysis requests

### POST /api/code
Handle code generation requests

### POST /api/docs
Handle document analysis requests

### GET /api/health
Health check endpoint (returns OpenExecutive connection status)

## Configuration

### OpenExecutive Environment Variables

Edit `OpenExecutive/.env`:

- `ANTHROPIC_API_KEY`: Required for AI responses (get from https://console.anthropic.com/)
- `EXEC_EMAIL_ADDRESS`: Email address for the executive
- `USER_TIMEZONE`: Timezone (optional, defaults to system timezone)

### AI Multi-App Environment Variables

Edit `server/.env`:

- `OPENEXECUTIVE_API_URL`: OpenExecutive API URL (default: http://localhost:8000)
- `OPENEXECUTIVE_API_KEY`: Optional API key if OpenExecutive requires authentication

## Troubleshooting

### OpenExecutive won't start
- Ensure Python 3.11+ is installed
- Check that all dependencies are installed with `uv sync`
- Verify timezone libraries are installed (`pytz`, `tzdata`)

### AI responses show errors
- Verify OpenExecutive is running on port 8000
- Check that `ANTHROPIC_API_KEY` is set in `OpenExecutive/.env`
- Ensure the API key is valid and active

### Connection refused errors
- Make sure OpenExecutive is started before AI Multi-App
- Check that port 8000 is not in use by another application
- Verify firewall settings allow localhost connections

## Notes

- File uploads are limited to 16MB
- Uploaded files are stored in the `server/uploads` directory
- The application works in demo mode without OpenExecutive, but AI features require it
- OpenExecutive requires a valid Anthropic API key for real AI responses

## License

MIT
