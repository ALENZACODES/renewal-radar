import {answerLocalMortgageQuestion} from './helper-answers.js';
import {LocalEvidenceReview} from './helper-review.js';

export const helperStorageKey = 'rr_local_helper_v17';
const maximumMessages = 40;
const maximumStoredBytes = 180000;

export class LocalMortgageConversation {
  constructor({getWorkspace = () => ({}), storage = null, clock = () => new Date().toISOString()} = {}) {
    this.getWorkspace = getWorkspace;
    this.storage = storage;
    this.clock = clock;
    this.messages = [];
    this.remember = false;
    this.storageError = null;
    this.review = new LocalEvidenceReview({clock});
    this.sequence = 0;
  }

  ask(question) {
    const previous = [...this.messages].reverse().find(message => message.role === 'assistant' && message.answer?.intent);
    const answer = answerLocalMortgageQuestion(question, this.getWorkspace(), {previousIntent: previous?.answer.intent});
    const recordedAt = this.clock();
    this.messages.push({id: ++this.sequence, role: 'user', text: question.trim(), recordedAt});
    this.messages.push({id: ++this.sequence, role: 'assistant', answer, recordedAt});
    if (this.messages.length > maximumMessages) this.messages.splice(0, this.messages.length - maximumMessages);
    this.persist();
    return answer;
  }

  decide(targetId, decision, note = '') {
    const record = this.review.decide(this.getWorkspace(), targetId, decision, note);
    this.persist();
    return record;
  }

  setRemember(enabled) {
    if (typeof enabled !== 'boolean') throw new TypeError('Storage consent must be a boolean');
    this.remember = enabled;
    if (enabled) this.persist();
    else this.removeStored();
  }

  packet() {
    return {
      provider: 'local-mortgage-conversation-v17',
      exportedAt: this.clock(),
      messages: this.messages.map(message => structuredClone(message)),
      review: this.review.export(this.getWorkspace()),
      networkRequired: false,
      cloudModelUsed: false,
      rawOcrIncluded: false,
    };
  }

  persist() {
    this.storageError = null;
    if (!this.remember) return false;
    if (!this.storage) {
      this.storageError = 'Local conversation storage is unavailable';
      return false;
    }
    try {
      const serialized = JSON.stringify(this.packet());
      if (serialized.length > maximumStoredBytes) throw new RangeError('Conversation is too large to store locally');
      this.storage.setItem(helperStorageKey, serialized);
      return true;
    } catch (error) {
      this.storageError = error.message || 'Conversation could not be stored';
      return false;
    }
  }

  removeStored() {
    this.storageError = null;
    try {
      this.storage?.removeItem(helperStorageKey);
    } catch {
      this.storageError = 'Stored conversation could not be removed';
    }
  }

  clear() {
    this.messages = [];
    this.sequence = 0;
    this.review.clear();
    this.removeStored();
  }

  restore() {
    if (!this.storage) return false;
    try {
      const serialized = this.storage.getItem(helperStorageKey);
      if (!serialized) return false;
      if (serialized.length > maximumStoredBytes) throw new RangeError('Stored conversation exceeds the size limit');
      const packet = JSON.parse(serialized);
      if (packet.provider !== 'local-mortgage-conversation-v17' || !Array.isArray(packet.messages)) {
        throw new TypeError('Stored conversation is invalid');
      }
      const messages = packet.messages.slice(-maximumMessages);
      for (const message of messages) {
        if (!message || !['user', 'assistant'].includes(message.role)
            || !Number.isSafeInteger(message.id) || message.id < 1
            || typeof message.recordedAt !== 'string' || message.recordedAt.length > 40) {
          throw new TypeError('Stored message is invalid');
        }
        if (message.role === 'user' && (typeof message.text !== 'string' || message.text.length > 1000)) {
          throw new TypeError('Stored question is invalid');
        }
        if (message.role === 'assistant' && (!message.answer?.local || !Array.isArray(message.answer.claims)
            || message.answer.claims.length > 40 || message.answer.claims.some(claim => typeof claim.text !== 'string' || claim.text.length > 2000))) {
          throw new TypeError('Stored answer is invalid');
        }
      }
      const review = new LocalEvidenceReview({clock: this.clock});
      review.restore(packet.review);
      this.review = review;
      this.messages = structuredClone(messages);
      this.sequence = Math.max(0, ...messages.map(message => message.id));
      this.remember = true;
      this.storageError = null;
      return true;
    } catch (error) {
      this.storageError = error.message || 'Stored conversation could not be restored';
      return false;
    }
  }
}
