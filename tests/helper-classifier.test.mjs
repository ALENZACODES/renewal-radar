import {test} from 'node:test';
import assert from 'node:assert/strict';
import {normalizeHelperQuestion, helperTokens, trainHelperClassifier, rankHelperIntents, classifyHelperQuestion, helperModelSummary} from '../frontend/js/helper-classifier.js';

const heldOut = [
  ['Tell me my contract rate', 'contract_rate'],
  ['Where can I see my registered contract rate?', 'contract_rate'],
  ['What original posted rate did the lender use?', 'posted_rate'],
  ['Show my posted rate', 'posted_rate'],
  ['What is the contract discount in bps?', 'discount'],
  ['Does posted minus contract equal my discount?', 'discount'],
  ['Explain IRD', 'ird'],
  ['What does intrest rate differental mean?', 'ird'],
  ['Will an early break penalty apply?', 'ird'],
  ['When was my mortgage funded?', 'mortgage_date'],
  ['What is my original mortgage date?', 'mortgage_date'],
  ['When is the renewal effective date?', 'renewal_date'],
  ['When is my new term start date?', 'renewal_date'],
  ['What maturity date is written?', 'maturity'],
  ['When will the mortgage mature?', 'maturity'],
  ['What is my term?', 'term'],
  ['Tell me the length of this mortgage term', 'term'],
  ['How much amortisation remains?', 'amortization'],
  ['Explain my remaining repayment period', 'amortization'],
  ['What new renewal rate is offered?', 'renewal_rate'],
  ['Read my renewal offer rate', 'renewal_rate'],
  ['What current rate am I paying?', 'current_rate'],
  ['What was the old interest rate?', 'current_rate'],
  ['What is my outstanding principal balance?', 'balance'],
  ['How much do I owe?', 'balance'],
  ['What is the monthly payment amount?', 'payment'],
  ['Are taxes included in payments?', 'payment'],
  ['How much interest could the alternative save?', 'comparison'],
  ['Compare the alternative mortgage offers', 'comparison'],
  ['When must this offer be accepted?', 'expiry'],
  ['When is my offer expiry date?', 'expiry'],
  ['What needs review?', 'review'],
  ['Which extracted fields conflict?', 'review'],
  ['Hello mortgage helper', 'help'],
  ['Show the current prime rate', 'market'],
  ['What is the Bank of Canada policy rate?', 'market'],
];

for (const [question, intent] of heldOut) {
  test(`local model recognizes ${question}`, () => {
    const prediction = classifyHelperQuestion(question);
    assert.equal(prediction.intent, intent, JSON.stringify(prediction));
    assert.ok(prediction.confidence > 0.4);
  });
}

test('generic interest wording asks for clarification', () => {
  const result = classifyHelperQuestion('What is interest?');
  assert.equal(result.intent, null);
  assert.equal(result.reason, 'ambiguous');
  assert.ok(result.suggestions.length > 0);
});

test('unknown topics have no invented mortgage intent', () => {
  for (const question of ['Who won the baseball game?', 'Write a recipe for spaghetti', 'Translate Shakespeare into Klingon']) {
    assert.equal(classifyHelperQuestion(question).intent, null);
  }
});

test('blank questions are classified as empty', () => {
  assert.equal(classifyHelperQuestion('  ').reason, 'empty');
});

test('normalization repairs known mortgage OCR spellings', () => {
  assert.equal(normalizeHelperQuestion('Intrest rate differental and amortisation'), 'interest rate differential and amortization');
  assert.match(normalizeHelperQuestion('IRD'), /interest rate differential/);
});

test('tokens include informative adjacent word pairs', () => {
  const features = helperTokens('What is my contract rate?');
  assert.deepEqual(features, ['contract', 'rate', 'contract:rate']);
});

test('ranked intent probabilities are finite and normalized', () => {
  const result = rankHelperIntents('contract rate discount');
  assert.ok(result.ranked.every(item => Number.isFinite(item.score) && Number.isFinite(item.probability)));
  assert.ok(Math.abs(result.ranked.reduce((sum, item) => sum + item.probability, 0) - 1) < 1e-10);
});

test('a tiny independent training model supports discriminative vocabulary', () => {
  const model = trainHelperClassifier([
    {id: 'rates', label: 'Rates', examples: ['contract rate', 'posted interest rate']},
    {id: 'dates', label: 'Dates', examples: ['maturity date', 'funding start date']},
  ]);
  assert.equal(rankHelperIntents('funding date', model).ranked[0].id, 'dates');
  assert.equal(rankHelperIntents('contract rate', model).ranked[0].id, 'rates');
});

test('invalid training corpora are rejected', () => {
  assert.throws(() => trainHelperClassifier([]));
  assert.throws(() => trainHelperClassifier([{id: 'x', examples: []}]));
  assert.throws(() => trainHelperClassifier([{id: 'x', examples: ['rate']}, {id: 'x', examples: ['date']}]));
});

test('question length and input type are bounded', () => {
  assert.throws(() => classifyHelperQuestion('x'.repeat(1001)), RangeError);
  assert.throws(() => classifyHelperQuestion(null), TypeError);
  assert.throws(() => classifyHelperQuestion({text: 'rate'}), TypeError);
});

test('model summary identifies local inference and bundled training data', () => {
  const summary = helperModelSummary();
  assert.equal(summary.topicCount, 18);
  assert.equal(summary.trainingExamples, 144);
  assert.equal(summary.networkRequired, false);
  assert.match(summary.inference, /naive-bayes/);
});
