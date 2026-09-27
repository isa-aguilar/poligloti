"""GBNF grammar of the teacher's JSON reply contract.

llama.cpp-based servers accept a `grammar` field on /chat/completions that
restricts sampling to the given grammar. With AI_JSON_MODE=gbnf every teacher
turn is a valid contract object (reply, corrections, new_vocab,
suggested_followup and the optional revised), and backend/llm_parse.py becomes
a safety net instead of the usual path.

Only teacher turns use it. The post-session analyst, the mode 5 colleague,
reading generation and progress translation have other output shapes.
"""

from __future__ import annotations

TEACHER_GBNF = r"""root ::= "{" ws q "reply" q ws ":" ws string "," ws q "corrections" q ws ":" ws corrections "," ws q "new_vocab" q ws ":" ws vocab "," ws q "suggested_followup" q ws ":" ws string ("," ws q "revised" q ws ":" ws string)? ws "}"
corrections ::= "[" ws "]" | "[" ws correction (ws "," ws correction)* ws "]"
correction ::= "{" ws q "original" q ws ":" ws string "," ws q "corrected" q ws ":" ws string ("," ws q "note" q ws ":" ws string)? ws "}"
vocab ::= "[" ws "]" | "[" ws vocabitem (ws "," ws vocabitem)* ws "]"
vocabitem ::= "{" ws q "term" q ws ":" ws string ("," ws q "translation" q ws ":" ws string)? ("," ws q "example" q ws ":" ws string)? ws "}"
string ::= q chars q
chars ::= ([^"\\\x00-\x1f] | "\\" (["\\/bfnrt] | "u" [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F]))*
q ::= "\""
ws ::= [ \t\n]?
"""
