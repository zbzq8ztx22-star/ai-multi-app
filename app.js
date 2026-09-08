// Tab navigation
const navBtns = document.querySelectorAll('.nav-btn');
const tabContents = document.querySelectorAll('.tab-content');

navBtns.forEach(btn => {
    btn.addEventListener('click', () => {
        const tab = btn.dataset.tab;
        
        navBtns.forEach(b => b.classList.remove('active'));
        tabContents.forEach(c => c.classList.remove('active'));
        
        btn.classList.add('active');
        document.getElementById(tab).classList.add('active');
    });
});

// Sidebar toggle
const toggleBtn = document.getElementById('toggleSidebar');
const sidebar = document.querySelector('.sidebar');

toggleBtn.addEventListener('click', () => {
    sidebar.classList.toggle('collapsed');
});

// Chat functionality
const chatForm = document.getElementById('chatForm');
const chatInput = document.getElementById('chatInput');
const chatMessages = document.getElementById('chatMessages');
let chatHistory = [];

// Add initial message
addMessage('assistant', 'Hello! I\'m your AI assistant. How can I help you today?');

chatForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const message = chatInput.value.trim();
    if (!message) return;
    
    addMessage('user', message);
    chatInput.value = '';
    
    const loadingId = addLoading();
    
    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message, history: chatHistory })
        });
        
        const data = await response.json();
        removeLoading(loadingId);
        addMessage('assistant', data.response);
        
        chatHistory.push({ role: 'user', content: message });
        chatHistory.push({ role: 'assistant', content: data.response });
    } catch (error) {
        removeLoading(loadingId);
        addMessage('assistant', 'Sorry, there was an error processing your request.');
    }
});

function addMessage(role, content) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;
    messageDiv.innerHTML = `
        <div class="message-content">${escapeHtml(content)}</div>
    `;
    chatMessages.appendChild(messageDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function addLoading() {
    const loadingId = 'loading-' + Date.now();
    const loadingDiv = document.createElement('div');
    loadingDiv.id = loadingId;
    loadingDiv.className = 'message assistant';
    loadingDiv.innerHTML = `
        <div class="message-content loading">Thinking</div>
    `;
    chatMessages.appendChild(loadingDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return loadingId;
}

function removeLoading(id) {
    const loading = document.getElementById(id);
    if (loading) loading.remove();
}

// Vision functionality
const imageDropZone = document.getElementById('imageDropZone');
const imageInput = document.getElementById('imageInput');
const selectImageBtn = document.getElementById('selectImageBtn');
const imagePreview = document.getElementById('imagePreview');
const previewImg = document.getElementById('previewImg');
const analyzeImageBtn = document.getElementById('analyzeImageBtn');
const clearImageBtn = document.getElementById('clearImageBtn');
const imageAnalysis = document.getElementById('imageAnalysis');
let selectedImage = null;

selectImageBtn.addEventListener('click', () => imageInput.click());

imageInput.addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (file) handleImageFile(file);
});

imageDropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    imageDropZone.style.borderColor = '#0ea5e9';
});

imageDropZone.addEventListener('dragleave', () => {
    imageDropZone.style.borderColor = '#4b5563';
});

imageDropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    imageDropZone.style.borderColor = '#4b5563';
    const file = e.dataTransfer.files[0];
    if (file && file.type.startsWith('image/')) {
        handleImageFile(file);
    }
});

function handleImageFile(file) {
    selectedImage = file;
    const reader = new FileReader();
    reader.onload = (e) => {
        previewImg.src = e.target.result;
        document.querySelector('.upload-placeholder').style.display = 'none';
        imagePreview.style.display = 'block';
        imageAnalysis.style.display = 'none';
    };
    reader.readAsDataURL(file);
}

analyzeImageBtn.addEventListener('click', async () => {
    if (!selectedImage) return;
    
    analyzeImageBtn.textContent = 'Analyzing...';
    analyzeImageBtn.disabled = true;
    
    const formData = new FormData();
    formData.append('image', selectedImage);
    
    try {
        const response = await fetch('/api/vision', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        imageAnalysis.innerHTML = `
            <h3>✨ Analysis Results</h3>
            <p>${escapeHtml(data.analysis)}</p>
        `;
        imageAnalysis.style.display = 'block';
    } catch (error) {
        imageAnalysis.innerHTML = `
            <h3>❌ Error</h3>
            <p>Failed to analyze image. Please try again.</p>
        `;
        imageAnalysis.style.display = 'block';
    } finally {
        analyzeImageBtn.textContent = 'Analyze Image';
        analyzeImageBtn.disabled = false;
    }
});

clearImageBtn.addEventListener('click', () => {
    selectedImage = null;
    previewImg.src = '';
    imagePreview.style.display = 'none';
    document.querySelector('.upload-placeholder').style.display = 'block';
    imageAnalysis.style.display = 'none';
    imageInput.value = '';
});

// Code generation functionality
const languageSelect = document.getElementById('languageSelect');
const codePrompt = document.getElementById('codePrompt');
const generateCodeBtn = document.getElementById('generateCodeBtn');
const codeResult = document.getElementById('codeResult');
const generatedCode = document.getElementById('generatedCode');
const copyCodeBtn = document.getElementById('copyCodeBtn');

generateCodeBtn.addEventListener('click', async () => {
    const prompt = codePrompt.value.trim();
    const language = languageSelect.value;
    
    if (!prompt) return;
    
    generateCodeBtn.textContent = 'Generating...';
    generateCodeBtn.disabled = true;
    
    try {
        const response = await fetch('/api/code', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt, language })
        });
        
        const data = await response.json();
        generatedCode.textContent = data.code;
        codeResult.style.display = 'block';
    } catch (error) {
        generatedCode.textContent = '// Error generating code. Please try again.';
        codeResult.style.display = 'block';
    } finally {
        generateCodeBtn.textContent = 'Generate Code';
        generateCodeBtn.disabled = false;
    }
});

copyCodeBtn.addEventListener('click', () => {
    navigator.clipboard.writeText(generatedCode.textContent);
    copyCodeBtn.textContent = 'Copied!';
    setTimeout(() => {
        copyCodeBtn.textContent = 'Copy';
    }, 2000);
});

// Document analysis functionality
const docInput = document.getElementById('docInput');
const selectDocBtn = document.getElementById('selectDocBtn');
const fileInfo = document.getElementById('fileInfo');
const fileName = document.getElementById('fileName');
const clearDocBtn = document.getElementById('clearDocBtn');
const analyzeDocBtn = document.getElementById('analyzeDocBtn');
const docAnalysis = document.getElementById('docAnalysis');
let selectedDoc = null;

selectDocBtn.addEventListener('click', () => docInput.click());

docInput.addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (file) handleDocFile(file);
});

function handleDocFile(file) {
    selectedDoc = file;
    fileName.textContent = file.name;
    document.querySelector('.upload-placeholder').style.display = 'none';
    fileInfo.style.display = 'flex';
    analyzeDocBtn.style.display = 'block';
    docAnalysis.style.display = 'none';
}

clearDocBtn.addEventListener('click', () => {
    selectedDoc = null;
    fileName.textContent = '';
    fileInfo.style.display = 'none';
    analyzeDocBtn.style.display = 'none';
    docAnalysis.style.display = 'none';
    document.querySelector('.upload-placeholder').style.display = 'block';
    docInput.value = '';
});

analyzeDocBtn.addEventListener('click', async () => {
    if (!selectedDoc) return;
    
    analyzeDocBtn.textContent = 'Analyzing...';
    analyzeDocBtn.disabled = true;
    
    const formData = new FormData();
    formData.append('document', selectedDoc);
    
    try {
        const response = await fetch('/api/docs', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        docAnalysis.innerHTML = `
            <h3>✨ Analysis Results</h3>
            <p>${escapeHtml(data.analysis)}</p>
        `;
        docAnalysis.style.display = 'block';
    } catch (error) {
        docAnalysis.innerHTML = `
            <h3>❌ Error</h3>
            <p>Failed to analyze document. Please try again.</p>
        `;
        docAnalysis.style.display = 'block';
    } finally {
        analyzeDocBtn.textContent = 'Analyze Document';
        analyzeDocBtn.disabled = false;
    }
});

// Utility function to escape HTML
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
