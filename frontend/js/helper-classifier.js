import {helperTopics, helperModelVersion} from './helper-model.js';

const stopWords = new Set('a an the is are was were be been my me i you your we our it this that to from of for on in with please can could would should show read find explain what which how much does do did'.split(' '));

export function normalizeHelperQuestion(value) {
  if (typeof value !== 'string') throw new TypeError('Enter a text question');
  if (value.length > 1000) throw new RangeError('Keep the question under 1,000 characters');
  return value.normalize('NFKD').replace(/[\u0300-\u036f]/g, '')
    .toLowerCase().replace(/\bintrest\b/g, 'interest')
    .replace(/\bdifferental\b|\bdif{1,2}erencial\b/g, 'differential')
    .replace(/\bird\b/g, 'interest rate differential')
    .replace(/\bamortisation\b/g, 'amortization')
    .replace(/\bcontractual\b/g, 'contract')
    .replace(/\bremains\b/g, 'remaining')
    .replace(/\bowe\b/g, 'owing')
    .replace(/\b3\b/g, 'three').replace(/\bbps\b/g, 'basis points')
    .replace(/[^a-z0-9\s?;]/g, ' ').replace(/\s+/g, ' ').trim();
}

export function helperTokens(question) {
  const words = normalizeHelperQuestion(question).split(/[\s?;]+/)
    .filter(word => word && !stopWords.has(word) && !/^\d+$/.test(word));
  const features = [...words];
  for (let index = 0; index + 1 < words.length; index++) {
    features.push(words[index] + ':' + words[index + 1]);
  }
  return features;
}

export function trainHelperClassifier(topics = helperTopics) {
  const vocabulary = new Set();
  const classes = [];
  const ids = new Set();
  let documents = 0;
  for (const topic of topics) {
    if (!topic.id || ids.has(topic.id) || !Array.isArray(topic.examples) || !topic.examples.length) {
      throw new TypeError('Each topic needs a unique id and training examples');
    }
    ids.add(topic.id);
    const counts = new Map();
    let total = 0;
    for (const example of topic.examples) {
      for (const token of helperTokens(example)) {
        vocabulary.add(token);
        counts.set(token, (counts.get(token) || 0) + 1);
        total++;
      }
    }
    documents += topic.examples.length;
    classes.push({id: topic.id, label: topic.label, counts, total, documents: topic.examples.length});
  }
  if (!classes.length || !vocabulary.size) throw new TypeError('Training vocabulary is empty');
  const weights = new Map();
  for (const feature of vocabulary) {
    const occurrences = classes.filter(topic => topic.counts.has(feature)).length;
    weights.set(feature, 1 + Math.log((classes.length + 1) / (occurrences + 1)));
  }
  return {version: helperModelVersion, classes, vocabulary, documents, weights};
}

const bundledModel = trainHelperClassifier();

export function rankHelperIntents(question, model = bundledModel) {
  const features = helperTokens(question);
  const known = features.filter(feature => model.vocabulary.has(feature));
  if (!known.length) return {ranked: [], knownFeatures: [], coverage: 0};
  const frequencies = new Map();
  for (const feature of known) frequencies.set(feature, Math.min(3, (frequencies.get(feature) || 0) + 1));
  const ranked = model.classes.map(topic => {
    let score = Math.log(topic.documents / model.documents);
    for (const [feature, count] of frequencies) {
      score += count * model.weights.get(feature) * Math.log(((topic.counts.get(feature) || 0) + 1) / (topic.total + model.vocabulary.size));
    }
    return {id: topic.id, label: topic.label, score};
  }).sort((left, right) => right.score - left.score || left.id.localeCompare(right.id));
  const maximum = ranked[0].score;
  const denominator = ranked.reduce((sum, item) => sum + Math.exp(item.score - maximum), 0);
  for (const item of ranked) item.probability = Math.exp(item.score - maximum) / denominator;
  return {ranked, knownFeatures: [...frequencies.keys()], coverage: known.length / features.length};
}

export function classifyHelperQuestion(question) {
  const normalized = normalizeHelperQuestion(question);
  if (!normalized) return {intent: null, reason: 'empty', suggestions: [], confidence: 0};
  const result = rankHelperIntents(normalized);
  const [first, second] = result.ranked;
  if (!first) return {intent: null, reason: 'unknown', suggestions: [], confidence: 0};
  const margin = first.probability - (second?.probability || 0);
  const confident = first.probability >= 0.4 && margin >= 0.12 && result.coverage >= 0.2;
  return {
    intent: confident ? first.id : null,
    reason: confident ? 'classified' : 'ambiguous',
    confidence: first.probability,
    suggestions: result.ranked.slice(0, 3).map(item => ({id: item.id, label: item.label})),
    knownFeatures: result.knownFeatures,
    model: helperModelVersion,
  };
}

export function helperModelSummary() {
  return {
    version: bundledModel.version,
    topicCount: bundledModel.classes.length,
    trainingExamples: bundledModel.documents,
    vocabularySize: bundledModel.vocabulary.size,
    inference: 'idf-weighted-multinomial-naive-bayes',
    networkRequired: false,
  };
}
