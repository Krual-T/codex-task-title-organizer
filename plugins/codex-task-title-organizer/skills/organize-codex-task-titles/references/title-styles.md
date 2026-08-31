# Choose a title marker style

Every title uses exactly one leading marker grapheme, one ordinary space, and
four non-empty fields separated by `｜`:

`Marker Domain｜Project/repository key｜Work type｜Concrete object: purpose or symptom`

## Built-in styles

| Primary outcome | Color blocks (default) | Semantic icons |
| --- | --- | --- |
| Analysis or diagnosis | `🟥` | `🔎` |
| Fix or implementation | `🟦` | `🔧` |
| Validation or testing | `🟩` | `🧪` |
| Delivery or synchronization | `🟪` | `📦` |
| Review | `🟧` | `👀` |
| Documentation or reporting | `🟨` | `📝` |
| Environment, tooling, or automation | `🟫` | `⚙️` |

Color blocks are the automatic-checkpoint fallback. Semantic icons are used
only when requested explicitly, selected by active project instructions, or
already present in an otherwise compliant title.

## Custom styles

A custom style may define either one global marker, such as `◆`, or a complete
seven-category mapping matching the table above. Every custom value must be one
visible symbol or emoji grapheme and must not contain whitespace or `｜`.

Use distinct category markers unless the user explicitly requests one global
marker. Do not infer a private taxonomy. If a custom mapping is incomplete or
invalid at an automatic checkpoint, fall back to color blocks without blocking
the user's task.

## Migration

For a marker-only migration, replace only the leading marker. Preserve the
domain, project or repository key, work type, concrete object, language, and
meaning. Never prepend a second marker or silently convert a valid selected
style back to color blocks.
