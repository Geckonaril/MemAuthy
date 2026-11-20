"""Rule-based classification of memory blocks into rule / preference / information.

Deterministic, local and free (tier 0). Features are general linguistic cues for *persistent
directives*; they are deliberately not derived from benchmark phrasing (see ADR-0007):

* imperative opening ("Use …", "Always CC …", "Never …"), also after a ``For X, …`` frame
* obligation / modality ("must", "should", "make sure", "do not")
* persistence / future scope ("from now on", "for later …", "next time", "until revised")
* rule labels and nouns ("Routing convention: …", "policy", "procedure")
* preference cues ("prefers", "likes", "would rather")

A block is a RULE if it prescribes future behavior, a PREFERENCE if it attributes a liking to a
person, and INFORMATION otherwise (facts, logs, headings, metadata). Classification says nothing
about *authority*; that is the policy's job.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from memauthy.schema import RecordKind

# Base-form verbs that commonly open a directive in agent memory. General, not domain-specific.
IMPERATIVE_VERBS = frozenset(
    [
        "accept",
        "add",
        "adopt",
        "allow",
        "always",
        "apply",
        "approve",
        "archive",
        "ask",
        "assign",
        "attach",
        "avoid",
        "block",
        "call",
        "cap",
        "carry",
        "cc",
        "check",
        "cite",
        "clean",
        "close",
        "commit",
        "compress",
        "confirm",
        "copy",
        "create",
        "deny",
        "delete",
        "deploy",
        "disable",
        "do",
        "document",
        "don't",
        "draft",
        "email",
        "enable",
        "encrypt",
        "ensure",
        "escalate",
        "exclude",
        "file",
        "flag",
        "follow",
        "format",
        "forward",
        "give",
        "grant",
        "hold",
        "ignore",
        "include",
        "insert",
        "invite",
        "keep",
        "label",
        "limit",
        "link",
        "list",
        "load",
        "lock",
        "mark",
        "make",
        "mention",
        "merge",
        "monitor",
        "move",
        "never",
        "notify",
        "open",
        "pay",
        "place",
        "post",
        "prefer",
        "prepare",
        "prioritize",
        "provide",
        "push",
        "put",
        "rank",
        "read",
        "record",
        "redirect",
        "refer",
        "reject",
        "remember",
        "remove",
        "request",
        "require",
        "restart",
        "retry",
        "reply",
        "report",
        "respond",
        "return",
        "review",
        "rotate",
        "route",
        "run",
        "save",
        "schedule",
        "send",
        "set",
        "share",
        "sign",
        "skip",
        "sort",
        "start",
        "stop",
        "store",
        "submit",
        "summarize",
        "switch",
        "tag",
        "tell",
        "test",
        "transfer",
        "translate",
        "treat",
        "update",
        "upload",
        "use",
        "verify",
        "wait",
        "write",
    ]
)

_WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")
_LABEL_PREFIX = re.compile(r"^\s*(?:\*\*)?([A-Za-z][\w /-]{0,40}?)(?:\*\*)?\s*:\s+")
_FOR_FRAME = re.compile(
    r"^\s*(?:for|when|whenever|if|in|on|before|after|once|unless)\b[^,;:]{0,160}[,;:]\s*",
    re.IGNORECASE,
)

_OBLIGATION = re.compile(
    r"\b(must|should|shall|ought to|needs? to|has to|have to|is required to|are required to|"
    r"make sure|be sure to|ensure that|do not|don't|never|always|avoid|is to be|are to be)\b",
    re.IGNORECASE,
)
_PERSISTENCE = re.compile(
    r"\b(from now on|going forward|henceforth|in (?:the )?future|for (?:all )?(?:later|future|"
    r"subsequent|upcoming)|for the next|next time|later \w+|each time|every time|whenever|"
    r"by default|until (?:an? |the )?\w+ (?:revises|changes|updates|says)|until further notice|"
    r"permanently|standing)\b",
    re.IGNORECASE,
)
_RULE_NOUN = re.compile(
    r"\b(conventions?|polic(?:y|ies)|rules?|procedures?|instructions?|guidelines?|protocols?|"
    r"runbooks?|requirements?|workflow)\b",
    re.IGNORECASE,
)
_RULE_LABEL_WORDS = re.compile(
    r"(convention|policy|rule|procedure|instruction|guideline|protocol|runbook|requirement|"
    r"workflow|checklist|process|standard|important|reminder|todo|note to self)",
    re.IGNORECASE,
)
_PREFERENCE = re.compile(
    r"\b(prefers?|preferred|preferences?|likes?|dislikes?|loves?|hates?|wants?|would rather|"
    r"would like|favou?rite|is fond of|enjoys?|is happiest with)\b",
    re.IGNORECASE,
)
_PERSON_SUBJECT = re.compile(
    r"^\s*(?:the |our |my )?(user|owner|client|customer|team|maintainer|manager|i|we|they|he|she)"
    r"(?:'s)?\b",
    re.IGNORECASE,
)
_PREFERENCE_VERBS = frozenset({"prefer", "want", "like"})
_LOG_PREFIX = re.compile(r"^\s*(?:\d{4}-\d{2}-\d{2}|\d{1,2}:\d{2})\b")
_PAST_OPENING = re.compile(r"^\s*[A-Z][a-z]+ed\b")


@dataclass(frozen=True)
class Classification:
    kind: RecordKind
    confidence: float
    features: tuple[str, ...] = ()
    rule_score: float = 0.0
    preference_score: float = 0.0
    rationale: str = ""


@dataclass(frozen=True)
class RuleClassifier:
    """Weighted cue scoring. Weights and thresholds are fixed and documented in ADR-0007."""

    name: str = "rule-based-v0.1"
    rule_threshold: float = 3.0
    weak_rule_threshold: float = 1.5
    weights: dict[str, float] = field(
        default_factory=lambda: {
            "imperative_opening": 2.0,
            "obligation": 1.5,
            "persistence": 1.5,
            "rule_label": 1.5,
            "rule_noun": 0.5,
        }
    )

    def classify(self, text: str, block_kind: str | None = None) -> Classification:
        body = text.strip()
        if not body:
            return Classification(RecordKind.UNKNOWN, 0.0, rationale="empty block")
        if block_kind == "front_matter":
            return Classification(
                RecordKind.INFORMATION, 0.9, ("front_matter",), rationale="metadata"
            )
        if block_kind == "code":
            return Classification(RecordKind.INFORMATION, 0.6, ("code_block",), rationale="code")

        features = self._features(body)
        rule = sum(self.weights[f] for f in features if f in self.weights)
        pref = 2.0 if "preference" in features else 0.0
        if pref and "person_subject" in features:
            pref += 1.0

        if pref >= 2.0 and pref >= rule:
            kind, conf = RecordKind.PREFERENCE, min(0.6 + 0.1 * pref, 0.9)
        elif rule >= self.rule_threshold:
            kind, conf = RecordKind.RULE, min(0.5 + 0.1 * rule, 0.95)
        elif (
            rule >= self.weak_rule_threshold
            and set(features) & {"obligation", "persistence", "imperative_opening", "rule_label"}
            and not set(features) & {"log_entry", "past_opening"}
        ):
            kind, conf = RecordKind.RULE, 0.55
        else:
            kind = RecordKind.INFORMATION
            conf = 0.8 if {"log_entry", "past_opening"} & set(features) or rule == 0 else 0.55
        rationale = f"rule={rule:.1f} pref={pref:.1f} features={','.join(features) or '-'}"
        return Classification(kind, round(conf, 3), tuple(features), rule, pref, rationale)

    @staticmethod
    def _features(body: str) -> list[str]:
        feats: list[str] = []
        text = body
        label = _LABEL_PREFIX.match(text)
        if label and _RULE_LABEL_WORDS.search(label.group(1)):
            feats.append("rule_label")
        if label:
            text = text[label.end() :]
        frame = _FOR_FRAME.match(text)
        clause = text[frame.end() :] if frame else text
        first = _WORD.match(clause.lstrip("*_>`- "))
        opening = first.group(0).lower() if first else ""
        if opening in IMPERATIVE_VERBS:
            feats.append("imperative_opening")
        if _OBLIGATION.search(body):
            feats.append("obligation")
        if _PERSISTENCE.search(body):
            feats.append("persistence")
        if _RULE_NOUN.search(body) and "rule_label" not in feats:
            feats.append("rule_noun")
        # "Prefer X" as an imperative is a directive, not a stated preference.
        if _PREFERENCE.search(body) and opening not in _PREFERENCE_VERBS:
            feats.append("preference")
        if _PERSON_SUBJECT.match(body):
            feats.append("person_subject")
        if _LOG_PREFIX.match(body):
            feats.append("log_entry")
        if _PAST_OPENING.match(body):
            feats.append("past_opening")
        return feats


DEFAULT_CLASSIFIER = RuleClassifier()


def classify(text: str, block_kind: str | None = None) -> Classification:
    return DEFAULT_CLASSIFIER.classify(text, block_kind)
