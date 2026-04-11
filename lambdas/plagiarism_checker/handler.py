"""
Lambda: plagiarism_checker
Triggered by: API Gateway  POST /plagiarism
Compares two documents for text similarity.

Algorithm:
  1. Sentence-level matching — finds near-identical sentences using
     normalised Jaccard similarity on word n-grams (no ML model needed,
     runs fast inside Lambda with zero dependencies beyond stdlib).
  2. TF-IDF cosine similarity — overall document-level similarity score.
  3. Returns matched sentence pairs + per-document highlight spans + overall %.

No S3/SQS needed — documents are small enough to process synchronously.
Results are NOT stored (no DynamoDB write) — plagiarism checks are ephemeral.
"""

import json
import math
import re
import os
import string
from collections import Counter
from typing import List, Tuple, Dict

# Similarity threshold to flag a sentence pair as a match (0-1)
SENTENCE_MATCH_THRESHOLD = 0.5   # Jaccard on trigrams
# Minimum sentence length in words to bother comparing
MIN_SENTENCE_WORDS = 6


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def handler(event, context):
    try:
        body = _parse_body(event)
        text1 = body.get("text1", "").strip()
        text2 = body.get("text2", "").strip()
        name1 = body.get("name1", "Document 1")
        name2 = body.get("name2", "Document 2")

        if not text1 or not text2:
            return _err(400, "Both 'text1' and 'text2' are required.")
        if len(text1.split()) < 20 or len(text2.split()) < 20:
            return _err(400, "Both documents must be at least 20 words long.")

        result = compare_documents(text1, text2, name1, name2)
        return _ok(result)

    except ValueError as e:
        return _err(400, str(e))
    except Exception as e:
        print(f"[plagiarism] ERROR: {e}")
        return _err(500, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# CORE COMPARISON ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

def compare_documents(text1: str, text2: str, name1: str, name2: str) -> dict:
    # 1. Split into sentences
    sents1 = _split_sentences(text1)
    sents2 = _split_sentences(text2)

    # 2. Find matching sentence pairs
    matches = _find_matches(sents1, sents2)

    # 3. Overall cosine similarity (document level)
    cosine_sim = _cosine_similarity(text1, text2)

    # 4. Coverage: what % of doc1 sentences have a match in doc2?
    matched_idx1 = set(m["idx1"] for m in matches)
    matched_idx2 = set(m["idx2"] for m in matches)

    words1 = len(text1.split())
    words2 = len(text2.split())

    # Weighted similarity: blend cosine + sentence coverage
    sent_coverage = len(matched_idx1) / max(len(sents1), 1)
    similarity_pct = round((cosine_sim * 0.5 + sent_coverage * 0.5) * 100, 1)

    # 5. Build highlight spans for the frontend
    highlights1 = _build_highlights(text1, sents1, matched_idx1)
    highlights2 = _build_highlights(text2, sents2, matched_idx2)

    # 6. Verdict
    verdict, verdict_color = _verdict(similarity_pct)

    return {
        "similarity_pct":   similarity_pct,
        "cosine_similarity": round(cosine_sim * 100, 1),
        "sentence_coverage": round(sent_coverage * 100, 1),
        "verdict":          verdict,
        "verdict_color":    verdict_color,
        "match_count":      len(matches),
        "doc1": {
            "name":       name1,
            "word_count": words1,
            "sent_count": len(sents1),
            "text":       text1,
            "highlights": highlights1,   # list of {start, end, match_id, similarity}
        },
        "doc2": {
            "name":       name2,
            "word_count": words2,
            "sent_count": len(sents2),
            "text":       text2,
            "highlights": highlights2,
        },
        "matches": [
            {
                "id":         i,
                "text1":      m["sent1"],
                "text2":      m["sent2"],
                "similarity": round(m["similarity"] * 100, 1),
            }
            for i, m in enumerate(matches)
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# SENTENCE MATCHING
# ═══════════════════════════════════════════════════════════════════════════════

def _split_sentences(text: str) -> List[str]:
    """Split text into sentences, filtering out very short ones."""
    raw = re.split(r'(?<=[.!?])\s+', text.strip())
    result = []
    for s in raw:
        s = s.strip()
        if len(s.split()) >= MIN_SENTENCE_WORDS:
            result.append(s)
    return result


def _ngrams(words: List[str], n: int) -> Counter:
    return Counter(tuple(words[i:i+n]) for i in range(len(words) - n + 1))


def _normalise(text: str) -> List[str]:
    """Lowercase, strip punctuation, split into words."""
    text = text.lower()
    text = text.translate(str.maketrans("", "", string.punctuation))
    return text.split()


def _jaccard_trigram(s1: str, s2: str) -> float:
    """Jaccard similarity on word trigrams."""
    w1 = _normalise(s1)
    w2 = _normalise(s2)
    if len(w1) < 3 or len(w2) < 3:
        # Fall back to unigram Jaccard for short sentences
        set1, set2 = set(w1), set(w2)
        if not set1 and not set2:
            return 0.0
        return len(set1 & set2) / len(set1 | set2)
    g1 = _ngrams(w1, 3)
    g2 = _ngrams(w2, 3)
    intersection = sum((g1 & g2).values())
    union        = sum((g1 | g2).values())
    return intersection / union if union else 0.0


def _find_matches(sents1: List[str], sents2: List[str]) -> List[Dict]:
    """
    For each sentence in doc1, find the best matching sentence in doc2.
    Returns only pairs above the threshold, deduplicated (greedy).
    """
    used2   = set()
    matches = []

    for i, s1 in enumerate(sents1):
        best_score = SENTENCE_MATCH_THRESHOLD
        best_j     = -1
        for j, s2 in enumerate(sents2):
            if j in used2:
                continue
            score = _jaccard_trigram(s1, s2)
            if score > best_score:
                best_score = score
                best_j     = j
        if best_j >= 0:
            used2.add(best_j)
            matches.append({
                "idx1":       i,
                "idx2":       best_j,
                "sent1":      sents1[i],
                "sent2":      sents2[best_j],
                "similarity": best_score,
            })

    # Sort by similarity descending
    matches.sort(key=lambda m: m["similarity"], reverse=True)
    return matches


# ═══════════════════════════════════════════════════════════════════════════════
# TF-IDF COSINE SIMILARITY (document level)
# ═══════════════════════════════════════════════════════════════════════════════

_STOPWORDS = {
    "the","a","an","and","or","but","in","on","at","to","for","of","with",
    "is","are","was","were","be","been","being","have","has","had","do","does",
    "did","will","would","could","should","may","might","shall","can","this",
    "that","these","those","it","its","i","you","he","she","we","they","their",
    "our","your","my","his","her","not","no","so","as","by","from","up","about",
    "into","through","during","before","after","above","below","between","each",
    "more","also","than","then","when","where","who","which","how","all","both",
}

def _tfidf_vector(text: str) -> Dict[str, float]:
    words = _normalise(text)
    words = [w for w in words if w not in _STOPWORDS and len(w) > 2]
    tf    = Counter(words)
    total = sum(tf.values()) or 1
    return {w: c / total for w, c in tf.items()}


def _cosine_similarity(text1: str, text2: str) -> float:
    v1 = _tfidf_vector(text1)
    v2 = _tfidf_vector(text2)
    common = set(v1) & set(v2)
    if not common:
        return 0.0
    dot     = sum(v1[w] * v2[w] for w in common)
    mag1    = math.sqrt(sum(x**2 for x in v1.values()))
    mag2    = math.sqrt(sum(x**2 for x in v2.values()))
    if mag1 == 0 or mag2 == 0:
        return 0.0
    return dot / (mag1 * mag2)


# ═══════════════════════════════════════════════════════════════════════════════
# HIGHLIGHT SPAN BUILDER
# ═══════════════════════════════════════════════════════════════════════════════

def _build_highlights(full_text: str, sentences: List[str], matched_indices: set) -> List[Dict]:
    """
    For each matched sentence, find its character offset in full_text.
    Returns list of {start, end, match_id} for the frontend to render.
    """
    highlights = []
    search_from = 0
    match_id_map = {idx: mid for mid, idx in enumerate(sorted(matched_indices))}

    for i, sent in enumerate(sentences):
        if i not in matched_indices:
            continue
        # Find sentence in full text (approximate — strip leading/trailing spaces)
        needle = sent[:40]  # use first 40 chars to locate
        pos    = full_text.find(needle, search_from)
        if pos == -1:
            pos = full_text.find(needle)  # retry from start
        if pos == -1:
            continue
        highlights.append({
            "start":    pos,
            "end":      pos + len(sent),
            "match_id": match_id_map.get(i, i),
        })
        search_from = pos + len(sent)

    return highlights


# ═══════════════════════════════════════════════════════════════════════════════
# VERDICT
# ═══════════════════════════════════════════════════════════════════════════════

def _verdict(pct: float) -> Tuple[str, str]:
    if pct >= 75:  return "High plagiarism detected",   "red"
    if pct >= 50:  return "Significant overlap found",  "orange"
    if pct >= 25:  return "Some similarity detected",   "yellow"
    if pct >= 10:  return "Minor similarity",           "blue"
    return               "Documents appear original",   "green"


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_body(event) -> dict:
    import base64
    body = event.get("body", "") or ""
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8", errors="replace")
    try:
        return json.loads(body) if isinstance(body, str) else (body or {})
    except json.JSONDecodeError:
        return {}


def _ok(body: dict, code: int = 200) -> dict:
    return {
        "statusCode": code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }


def _err(code: int, msg: str) -> dict:
    return {
        "statusCode": code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps({"error": msg}),
    }
