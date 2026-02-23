"""
Chat UI styles — light theme only, simplified.
"""

from fasthtml.common import Style

CHAT_UI_STYLES = """
/* === Chat UI — Light Only === */
.chat-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #ffffff;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  overflow: hidden;
}

.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 1rem;
  background: #ffffff;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.chat-messages:empty::before {
  content: "Type a command or ask a question...";
  color: #94a3b8;
  text-align: center;
  padding: 2rem;
  font-style: italic;
}

/* === Messages === */
.chat-message {
  display: flex;
  flex-direction: column;
  max-width: 85%;
  animation: chat-message-in 0.3s ease-out;
}

.chat-message-content {
  padding: 0.75rem 1rem;
  border-radius: 1.125rem;
  font-size: 0.875rem;
  line-height: 1.5;
  word-wrap: break-word;
  position: relative;
}

.chat-message-content p { margin: 0 0 0.5rem 0; }
.chat-message-content p:last-child { margin-bottom: 0; }
.chat-message-content ul, .chat-message-content ol { margin: 0.5rem 0; padding-left: 1.5rem; }
.chat-message-content li { margin: 0.25rem 0; }

.chat-message-content code {
  background: #f1f5f9;
  padding: 0.125rem 0.25rem;
  border-radius: 0.25rem;
  font-size: 0.875em;
}

.chat-message-content pre {
  background: #f8fafc;
  color: #1e293b;
  border: 1px solid #e2e8f0;
  padding: 0.75rem;
  border-radius: 0.5rem;
  overflow-x: auto;
  margin: 0.5rem 0;
  font-size: 0.8rem;
  line-height: 1.5;
}

.chat-message-content pre code { background: none; padding: 0; color: inherit; }

.chat-message-content blockquote {
  border-left: 3px solid #e2e8f0;
  padding-left: 1rem;
  margin: 0.5rem 0;
  color: #64748b;
}

.chat-message-content h1, .chat-message-content h2,
.chat-message-content h3, .chat-message-content h4 {
  margin: 0.75rem 0 0.5rem 0; font-weight: 600; color: #1e293b;
}
.chat-message-content h1 { font-size: 1.25rem; }
.chat-message-content h2 { font-size: 1.125rem; }
.chat-message-content h3 { font-size: 1rem; }

.chat-message-content table {
  border-collapse: collapse;
  width: 100%;
  margin: 0.5rem 0;
  background: #ffffff;
}
.chat-message-content th, .chat-message-content td {
  border: 1px solid #e2e8f0;
  padding: 0.5rem;
  text-align: left;
  color: #1e293b;
}
.chat-message-content th {
  background: #f8fafc;
  font-weight: 600;
}

@keyframes chat-message-in {
  from { opacity: 0; transform: translateY(0.5rem); }
  to { opacity: 1; transform: translateY(0); }
}

.chat-user { align-self: flex-end; }
.chat-assistant { align-self: flex-start; }

.chat-user .chat-message-content {
  background: #3b82f6;
  color: #ffffff;
  border-bottom-right-radius: 0.375rem;
}

.chat-assistant .chat-message-content {
  background: #f8fafc;
  color: #1e293b;
  border: 1px solid #e2e8f0;
  border-bottom-left-radius: 0.375rem;
}

/* Streaming indicator */
.chat-streaming::after {
  content: '|';
  animation: chat-blink 1s infinite;
  opacity: 0.7;
}

@keyframes chat-blink {
  0%, 50% { opacity: 0.7; }
  51%, 100% { opacity: 0; }
}

/* === Input Form === */
.chat-input {
  padding: 1rem;
  background: #ffffff;
  border-top: 1px solid #e2e8f0;
}

.chat-status {
  min-height: 1rem;
  padding: 0.25rem 0;
  color: #64748b;
  font-size: 0.8rem;
  text-align: center;
}

#suggestion-buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  padding: 0.5rem;
  margin-bottom: 0.5rem;
}

.suggestion-btn {
  padding: 0.4rem 0.8rem;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 1rem;
  color: #3b82f6;
  font-size: 0.8rem;
  cursor: pointer;
  white-space: nowrap;
}

.suggestion-btn:hover {
  background: #3b82f6;
  color: white;
}

.chat-input-form {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 0.5rem;
  align-items: end;
  width: 100%;
}

.chat-input-field {
  width: 100%;
  padding: 0.75rem 1rem;
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
  background: #f8fafc;
  color: #1e293b;
  font-family: inherit;
  font-size: 0.9rem;
  line-height: 1.5;
  resize: none;
  min-height: 2.75rem;
  max-height: 12rem;
  overflow-y: hidden;
  box-sizing: border-box;
}

.chat-input-field:focus {
  outline: none;
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.15);
}

.chat-input-button {
  padding: 0.75rem 1.25rem;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 0.75rem;
  font-family: inherit;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  min-height: 2.75rem;
}

.chat-input-button:hover { background: #2563eb; }

/* === Tool/System Messages === */
.chat-tool { align-self: center; max-width: 70%; }

.chat-tool .chat-message-content {
  background: #f1f5f9;
  color: #64748b;
  font-size: 0.8rem;
  text-align: center;
  border-radius: 0.75rem;
  padding: 0.4rem 0.8rem;
}

/* === Error States === */
.chat-error .chat-message-content {
  background: #fef2f2;
  color: #dc2626;
  border: 1px solid #fecaca;
}

/* === Log Console (streaming command output) === */
.agui-log-console {
  max-height: 400px;
  overflow-y: auto;
}

.agui-log-pre {
  color: #475569;
  font-size: 0.8em;
  margin: 0;
  white-space: pre-wrap;
  font-family: ui-monospace, monospace;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  padding: 0.75rem;
  border-radius: 0.5rem;
}

/* === Responsive === */
@media (max-width: 768px) {
  .chat-message { max-width: 95%; }
}
"""


def get_chat_styles():
    """Get chat UI styles as a Style component."""
    return Style(CHAT_UI_STYLES)


def get_custom_theme(**theme_vars):
    """Generate custom theme CSS variable overrides."""
    css_vars = []
    for key, value in theme_vars.items():
        css_vars.append(f"--{key.replace('_', '-')}: {value};")
    return Style(f":root {{ {' '.join(css_vars)} }}")
