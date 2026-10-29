# Kazakh-first PWA and Latin-script search

User requirements: Kazakh default UI, Russian/English switch, persistent choice,
and script-independent lookup for current and future words and letters.

Implementation: local message dictionaries and React context (no service dependency),
accessible select in the existing top bar, document language and locale-aware dates.
Translate shell, login, upload/consent, moderation, playback, profile and offline shell.
User names, labels, comments and original stored arrays stay unchanged.

Search: shared pure Unicode-aware matching module, deriving keys from every catalog
label at runtime. Prioritize exact original spelling, then Latin forms with diacritics,
then common ASCII forms. Support case and combining Unicode marks. Do not choose a
different gesture silently when an ASCII key is ambiguous; expose the matching labels.
Use longest matching phrases, with separate messages for missing tokens.

Alphabet basis: government description of the improved alphabet:
https://www.gov.kz/org/mfa-omsk/press/news/details/153331
It documents ä/ö/ü/ū/ğ/ş. Compatibility lookup is not a claim that all 42 Cyrillic
characters have distinct official Latin equivalents. Accept ñ and ŋ for ң, common
digraph input, and preserve ambiguity. Translation of English/Russian vocabulary
into Kazakh is outside script transliteration.

Checks: pure matcher tests with arbitrary future labels and letters, collision tests,
dictionary coverage, browser default/switch/persistence, Latin playback and mobile fit,
existing UI regression scenarios in their explicit Russian locale, production build.
