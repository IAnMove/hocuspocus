export function splitPromptSchedule(prompt: string): string[] {
  return prompt
    .split(/\r?\n/)
    .map(line => line.trim())
    .filter(Boolean)
}
