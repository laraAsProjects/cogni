// Language list for the dropdowns - name (sent to the backend exactly as
// shown, matching what core.py's prompts and DEEPL_LANGUAGE_CODES expect)
// plus a flag emoji for quick visual scanning. Flags are a cosmetic
// simplification - several languages (English, German, French...) aren't
// tied to one country, so a "best representative" flag is picked rather
// than trying to be exhaustive. Not a closed set: "Other…" reveals a free
// text field, so any language cogni itself understands still works even
// if it's not in this convenience list (e.g. Northern Sámi).
//
// The first three (German, English, Norwegian) are listed first since
// they're the ones actually used day to day - everything else is
// alphabetical after that.
const LANGUAGES = [
  { name: "German", flag: "🇩🇪" },
  { name: "English", flag: "🇬🇧" },
  { name: "Norwegian", flag: "🇳🇴" },
  { name: "Arabic", flag: "🇸🇦" },
  { name: "Chinese", flag: "🇨🇳" },
  { name: "Czech", flag: "🇨🇿" },
  { name: "Danish", flag: "🇩🇰" },
  { name: "Dutch", flag: "🇳🇱" },
  { name: "Finnish", flag: "🇫🇮" },
  { name: "French", flag: "🇫🇷" },
  { name: "Greek", flag: "🇬🇷" },
  { name: "Hungarian", flag: "🇭🇺" },
  { name: "Italian", flag: "🇮🇹" },
  { name: "Japanese", flag: "🇯🇵" },
  { name: "Korean", flag: "🇰🇷" },
  { name: "Polish", flag: "🇵🇱" },
  { name: "Portuguese", flag: "🇵🇹" },
  { name: "Romanian", flag: "🇷🇴" },
  { name: "Russian", flag: "🇷🇺" },
  { name: "Spanish", flag: "🇪🇸" },
  { name: "Swedish", flag: "🇸🇪" },
  { name: "Turkish", flag: "🇹🇷" },
  { name: "Ukrainian", flag: "🇺🇦" },
];
