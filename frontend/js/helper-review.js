import {safeHelperContext, helperFingerprint} from './helper-context.js';

const decisions = new Set(['reviewed', 'needs_followup', 'unreviewed']);
const maximumEvents = 200;

export function helperReviewTargets(workspace) {
  const context = safeHelperContext(workspace);
  const targets = new Map();
  for (const [key, fact] of Object.entries(context.facts)) {
    targets.set('fact:' + key, {
      id: 'fact:' + key,
      label: key.replaceAll('_', ' '),
      type: 'fact', scope: fact.scope,
      status: fact.status,
      signature: helperFingerprint(fact),
      evidence: fact.evidence,
    });
  }
  for (const check of context.checks) {
    targets.set('check:' + check.id, {
      id: 'check:' + check.id,
      label: check.title,
      type: 'check', scope: check.scope,
      status: check.status,
      signature: helperFingerprint(check),
      evidence: check.evidence,
    });
  }
  return targets;
}

export class LocalEvidenceReview {
  constructor({clock = () => new Date().toISOString()} = {}) {
    this.clock = clock;
    this.records = new Map();
    this.events = [];
    this.revision = 0;
  }

  decide(workspace, targetId, decision, note = '') {
    if (!decisions.has(decision)) throw new TypeError('Choose a valid review decision');
    if (typeof note !== 'string' || note.length > 500) throw new RangeError('Keep review notes under 500 characters');
    const target = helperReviewTargets(workspace).get(targetId);
    if (!target) throw new TypeError('The source detail is no longer available');
    const record = {
      targetId, signature: target.signature, decision,
      note: note.trim(), recordedAt: this.clock(), revision: ++this.revision,
    };
    this.records.set(targetId, record);
    this.events.push({...record});
    if (this.events.length > maximumEvents) this.events.splice(0, this.events.length - maximumEvents);
    return {...record};
  }

  snapshot(workspace) {
    const targets = helperReviewTargets(workspace);
    const records = [];
    for (const target of targets.values()) {
      const stored = this.records.get(target.id);
      const current = stored?.signature === target.signature;
      records.push({
        ...target,
        decision: current ? stored.decision : 'unreviewed',
        note: current ? stored.note : '',
        stale: Boolean(stored && !current),
        recordedAt: current ? stored.recordedAt : null,
      });
    }
    return {
      revision: this.revision,
      records,
      summary: {
        reviewed: records.filter(record => record.decision === 'reviewed').length,
        followup: records.filter(record => record.decision === 'needs_followup').length,
        unreviewed: records.filter(record => record.decision === 'unreviewed').length,
        stale: records.filter(record => record.stale).length,
        conflicts: records.filter(record => record.status === 'conflict').length,
      },
      lenderCertification: false,
    };
  }

  export(workspace) {
    const context = safeHelperContext(workspace);
    return {
      provider: 'local-evidence-review-v17',
      exportedAt: this.clock(),
      documentName: context.documentName,
      contextFingerprint: context.fingerprint,
      review: this.snapshot(workspace),
      events: this.events.map(event => ({...event})),
      evidence: Object.values(context.ledger),
      rawOcrIncluded: false,
      lenderCertification: false,
    };
  }

  clear() {
    this.records.clear();
    this.events = [];
    this.revision = 0;
  }

  restore(packet) {
    if (!packet || packet.provider !== 'local-evidence-review-v17' || !Array.isArray(packet.events)) {
      throw new TypeError('Invalid local review data');
    }
    const restored = [];
    for (const event of packet.events.slice(-maximumEvents)) {
      if (!event || typeof event.targetId !== 'string' || event.targetId.length > 140
          || !/^[a-f0-9]{8}$/.test(event.signature) || !decisions.has(event.decision)
          || typeof event.note !== 'string' || event.note.length > 500
          || typeof event.recordedAt !== 'string' || event.recordedAt.length > 40
          || !Number.isSafeInteger(event.revision) || event.revision < 1) {
        throw new TypeError('Invalid local review event');
      }
      restored.push({
        targetId: event.targetId, signature: event.signature,
        decision: event.decision, note: event.note,
        recordedAt: event.recordedAt, revision: event.revision,
      });
    }
    let revision = 0;
    for (const event of restored) {
      if (event.revision <= revision) throw new TypeError('Review events are out of order');
      revision = event.revision;
    }
    this.clear();
    for (const event of restored) {
      this.records.set(event.targetId, event);
      this.events.push(event);
      this.revision = event.revision;
    }
  }
}
