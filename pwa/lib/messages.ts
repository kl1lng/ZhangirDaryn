import dictionary from './messages.json' with {type:'json'};
// Gesture labels and user content are not translated.
export const messages:Readonly<Record<string,readonly string[]>>=dictionary;
