import {LocalMortgageConversation} from './helper-conversation.js';
import {renderHelperPanel} from './helper-view.js';
import {readLocalHelperStorage} from './offline-workspace.js';

export function mountLocalMortgageHelper({getWorkspace, root = document.getElementById('local-helper')} = {}) {
  if (!root) throw new TypeError('Mortgage helper container is missing');
  const conversation = new LocalMortgageConversation({getWorkspace, storage: readLocalHelperStorage()});
  conversation.restore();
  let open = false;
  let error = null;
  let draft = '';
  let returnFocus = null;

  function render({focusQuestion = false, scrollMessages = false} = {}) {
    root.innerHTML = renderHelperPanel(conversation, getWorkspace(), {open, error, draft});
    const launcher = document.getElementById('helper-launcher');
    launcher?.setAttribute('aria-expanded', String(open));
    if (focusQuestion) root.querySelector('#helper-question')?.focus();
    if (scrollMessages) {
      const history = root.querySelector('.helper-history');
      if (history) history.scrollTop = history.scrollHeight;
    }
  }

  function submitQuestion(question) {
    try {
      conversation.ask(question);
      draft = '';
      error = null;
    } catch (failure) {
      error = failure.message || 'The question could not be answered';
    }
    render({focusQuestion: true, scrollMessages: true});
  }

  function close() {
    open = false;
    render();
    returnFocus?.focus();
  }

  function show() {
    returnFocus = document.activeElement;
    open = true;
    render({focusQuestion: true, scrollMessages: true});
  }

  function exportConversation() {
    const blob = new Blob([JSON.stringify(conversation.packet(), null, 2)], {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = 'renewal-radar-local-review.json';
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function click(event) {
    const suggestion = event.target.closest('[data-helper-suggestion]');
    if (suggestion) {
      submitQuestion(suggestion.dataset.helperSuggestion);
      return;
    }
    const command = event.target.closest('[data-helper-command]')?.dataset.helperCommand;
    if (command === 'close') close();
    if (command === 'clear') {
      conversation.clear();
      draft = '';
      error = null;
      render({focusQuestion: true});
    }
    if (command === 'export') exportConversation();
  }

  function submit(event) {
    if (event.target.id !== 'helper-question-form') return;
    event.preventDefault();
    submitQuestion(root.querySelector('#helper-question')?.value || '');
  }

  function input(event) {
    if (event.target.id === 'helper-question') draft = event.target.value;
  }

  function change(event) {
    const target = event.target;
    try {
      if (target.matches('[data-helper-remember]')) conversation.setRemember(target.checked);
      if (target.matches('[data-helper-decision]')) {
        const id = target.dataset.helperDecision;
        const note = target.closest('li').querySelector('[data-helper-note]')?.value || '';
        conversation.decide(id, target.value, note);
      }
      if (target.matches('[data-helper-note]')) {
        const id = target.dataset.helperNote;
        const decision = target.closest('li').querySelector('[data-helper-decision]')?.value || 'unreviewed';
        conversation.decide(id, decision, target.value);
      }
      error = null;
    } catch (failure) {
      error = failure.message;
    }
    render();
  }

  function keydown(event) {
    if (event.key === 'Escape' && open) {
      event.preventDefault();
      close();
    }
    if (event.target.id === 'helper-question' && event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      submitQuestion(event.target.value);
    }
  }

  const launcher = document.getElementById('helper-launcher');
  const toggle = () => open ? close() : show();
  launcher?.addEventListener('click', toggle);
  root.addEventListener('click', click);
  root.addEventListener('submit', submit);
  root.addEventListener('input', input);
  root.addEventListener('change', change);
  root.addEventListener('keydown', keydown);
  render();
  return {
    conversation, open: show, close,
    refresh: () => {if (open) render();},
    destroy: () => {
      launcher?.removeEventListener('click', toggle);
      root.removeEventListener('click', click);
      root.removeEventListener('submit', submit);
      root.removeEventListener('input', input);
      root.removeEventListener('change', change);
      root.removeEventListener('keydown', keydown);
      root.innerHTML = '';
    },
  };
}
