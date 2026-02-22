"""
Chat UI styles using CSS custom properties for theming.

Based on py-agui styles.py — light theme with dark mode via prefers-color-scheme.
"""

from fasthtml.common import Style

CHAT_UI_STYLES = """
/* === Chat UI CSS Custom Properties === */
:root {
  --chat-bg: #f8fafc;
  --chat-surface: #ffffff;
  --chat-border: #e2e8f0;
  --chat-text: #1e293b;
  --chat-text-muted: #64748b;
  --chat-primary: #3b82f6;
  --chat-primary-hover: #2563eb;
  --chat-user-bg: #3b82f6;
  --chat-user-text: #ffffff;
  --chat-assistant-bg: #f1f5f9;
  --chat-assistant-text: #1e293b;
  --chat-padding: 1rem;
  --chat-gap: 0.75rem;
  --chat-message-padding: 0.75rem 1rem;
  --chat-border-radius: 0.75rem;
  --chat-message-radius: 1.125rem;
  --chat-font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  --chat-font-size: 0.875rem;
  --chat-line-height: 1.5;
  --chat-transition: all 0.2s ease;
  --chat-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  --chat-shadow-lg: 0 4px 12px rgba(0, 0, 0, 0.15);
}

@media (prefers-color-scheme: dark) {
  :root {
    --chat-bg: #0f172a;
    --chat-surface: #1e293b;
    --chat-border: #334155;
    --chat-text: #f1f5f9;
    --chat-text-muted: #94a3b8;
    --chat-assistant-bg: #334155;
    --chat-assistant-text: #f1f5f9;
  }
}

/* === Chat Layout === */
.chat-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--chat-bg);
  font-family: var(--chat-font-family);
  overflow: hidden;
}

.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: var(--chat-padding);
  background: var(--chat-surface);
  display: flex;
  flex-direction: column;
  gap: var(--chat-gap);
}

.chat-messages:empty::before {
  content: "Type a command or ask a question...";
  color: var(--chat-text-muted);
  text-align: center;
  padding: 2rem;
  font-style: italic;
}

/* === Message Styles === */
.chat-message {
  display: flex;
  flex-direction: column;
  max-width: 85%;
  animation: chat-message-in 0.3s ease-out;
}

.chat-message-content p { margin: 0 0 0.5rem 0; }
.chat-message-content p:last-child { margin-bottom: 0; }
.chat-message-content ul, .chat-message-content ol { margin: 0.5rem 0; padding-left: 1.5rem; }
.chat-message-content li { margin: 0.25rem 0; }

.chat-message-content code {
  background: rgba(0, 0, 0, 0.1);
  padding: 0.125rem 0.25rem;
  border-radius: 0.25rem;
  font-size: 0.875em;
}

.chat-assistant .chat-message-content code { background: rgba(0, 0, 0, 0.05); }

.chat-message-content pre {
  background: #1e293b;
  color: #e2e8f0;
  padding: 1rem;
  border-radius: 0.5rem;
  overflow-x: auto;
  margin: 0.75rem 0;
  font-size: 0.875rem;
  line-height: 1.5;
}

.chat-message-content pre code { background: none; padding: 0; color: inherit; }

@media (prefers-color-scheme: dark) {
  .chat-message-content pre { background: #0f172a; border: 1px solid var(--chat-border); }
}

.chat-message-content blockquote {
  border-left: 3px solid var(--chat-border);
  padding-left: 1rem;
  margin: 0.5rem 0;
  color: var(--chat-text-muted);
}

.chat-message-content h1, .chat-message-content h2,
.chat-message-content h3, .chat-message-content h4 {
  margin: 0.75rem 0 0.5rem 0; font-weight: 600;
}
.chat-message-content h1 { font-size: 1.25rem; }
.chat-message-content h2 { font-size: 1.125rem; }
.chat-message-content h3 { font-size: 1rem; }

.chat-message-content table { border-collapse: collapse; width: 100%; margin: 0.5rem 0; }
.chat-message-content th, .chat-message-content td {
  border: 1px solid var(--chat-border); padding: 0.5rem; text-align: left;
}
.chat-message-content th { background: rgba(0, 0, 0, 0.05); font-weight: 600; }

@keyframes chat-message-in {
  from { opacity: 0; transform: translateY(0.5rem); }
  to { opacity: 1; transform: translateY(0); }
}

.chat-user { align-self: flex-end; }
.chat-assistant { align-self: flex-start; }

.chat-message-content {
  padding: var(--chat-message-padding);
  border-radius: var(--chat-message-radius);
  font-size: var(--chat-font-size);
  line-height: var(--chat-line-height);
  word-wrap: break-word;
  position: relative;
}

.chat-user .chat-message-content {
  background: var(--chat-user-bg);
  color: var(--chat-user-text);
  border-bottom-right-radius: 0.375rem;
}

.chat-assistant .chat-message-content {
  background: var(--chat-assistant-bg);
  color: var(--chat-assistant-text);
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
  padding: var(--chat-padding);
  background: var(--chat-surface);
  border-top: 1px solid var(--chat-border);
}

.chat-status {
  min-height: 1rem;
  padding: 0.25rem 0;
  color: var(--chat-text-muted);
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
  background: var(--chat-surface);
  border: 1px solid var(--chat-border);
  border-radius: 1rem;
  color: var(--chat-primary);
  font-size: 0.8rem;
  font-family: var(--chat-font-family);
  cursor: pointer;
  transition: var(--chat-transition);
  white-space: nowrap;
}

.suggestion-btn:hover {
  background: var(--chat-primary);
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
  border: 1px solid var(--chat-border);
  border-radius: var(--chat-border-radius);
  background: var(--chat-bg);
  color: var(--chat-text);
  font-family: var(--chat-font-family);
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
  border-color: var(--chat-primary);
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.15);
}

.chat-input-button {
  padding: 0.75rem 1.25rem;
  background: var(--chat-primary);
  color: white;
  border: none;
  border-radius: var(--chat-border-radius);
  font-family: var(--chat-font-family);
  font-size: var(--chat-font-size);
  font-weight: 500;
  cursor: pointer;
  min-height: 2.75rem;
}

.chat-input-button:hover { background: var(--chat-primary-hover); }

/* === Tool/System Messages === */
.chat-tool {
  align-self: center;
  max-width: 70%;
}

.chat-tool .chat-message-content {
  background: var(--chat-border);
  color: var(--chat-text-muted);
  font-size: 0.8rem;
  text-align: center;
  border-radius: var(--chat-border-radius);
  padding: 0.4rem 0.8rem;
}

/* === Error States === */
.chat-error .chat-message-content {
  background: #fef2f2;
  color: #dc2626;
  border: 1px solid #fecaca;
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
