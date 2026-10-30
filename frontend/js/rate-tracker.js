import {esc} from './ui.js';

export class RateRefreshController {
  constructor({fetchSnapshot, forceRefresh, onUpdate, onError = () => {},
    documentObject = globalThis.document, intervalMs = 300000,
    schedule = (callback, delay) => globalThis.setTimeout(callback, delay),
    cancel = id => globalThis.clearTimeout(id)}) {
    if (!Number.isFinite(intervalMs) || intervalMs < 30000) throw new RangeError('Rate polling interval is too short');
    this.fetchSnapshot = fetchSnapshot;
    this.forceRefresh = forceRefresh;
    this.onUpdate = onUpdate;
    this.onError = onError;
    this.documentObject = documentObject;
    this.intervalMs = intervalMs;
    this.schedule = schedule;
    this.cancel = cancel;
    this.running = false;
    this.timer = null;
    this.pending = null;
    this.visibility = () => {
      if (this.documentObject?.visibilityState !== 'hidden' && this.running) this.refresh();
    };
  }

  refresh(force = false) {
    if (this.pending) return this.pending;
    this.pending = Promise.resolve().then(() => force ? this.forceRefresh() : this.fetchSnapshot())
      .then(snapshot => {this.onUpdate(snapshot); return snapshot;})
      .catch(error => {this.onError(error); return null;})
      .finally(() => {this.pending = null;});
    return this.pending;
  }

  start() {
    if (this.running) return;
    this.running = true;
    this.documentObject?.addEventListener('visibilitychange', this.visibility);
    this.refresh();
    this.queue();
  }

  queue() {
    if (!this.running) return;
    this.timer = this.schedule(async () => {
      if (!this.running) return;
      if (this.documentObject?.visibilityState !== 'hidden') await this.refresh();
      this.queue();
    }, this.intervalMs);
  }

  stop() {
    this.running = false;
    if (this.timer !== null) this.cancel(this.timer);
    this.timer = null;
    this.documentObject?.removeEventListener('visibilitychange', this.visibility);
  }
}

export function rateTrackingView(snapshot) {
  if (!snapshot) return '';
  const status = snapshot.data_status === 'live-observation' ? 'Official observations retrieved'
    : snapshot.data_status === 'cached-stale' ? 'Cached observations' : 'Source unavailable';
  const changes = snapshot.changes || [];
  return `<section class="rate-tracking-band" aria-label="Automatic rate tracking">
    <h3>Rate tracking</h3>
    <p><strong>${esc(status)}</strong>${snapshot.checked_at ? ` &middot; Checked ${esc(snapshot.checked_at)}` : ''}</p>
    <p class="small">Refresh interval: ${Math.round((snapshot.refresh_interval_seconds || 900) / 60)} minutes. Verified lender pages: ${esc(snapshot.verified_bank_count || 0)}.</p>
    ${changes.length ? `<div class="table-scroll"><table class="semantic-facts"><thead><tr><th>Observation</th><th>Previous</th><th>Latest</th><th>Change</th><th>Published</th></tr></thead><tbody>
      ${changes.slice(0, 20).map(change => `<tr><td>${esc(change.label)}</td><td>${esc(change.previous)}%</td><td>${esc(change.current)}%</td><td>${esc(change.change_basis_points)} bps</td><td>${esc(change.observed_at)}</td></tr>`).join('')}
    </tbody></table></div>` : '<p>No rate changes recorded during this session.</p>'}
    ${(snapshot.warnings || []).map(warning => `<p role="status">${esc(warning)}</p>`).join('')}
  </section>`;
}
