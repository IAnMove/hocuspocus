/** Coming-soon skills stay in the list with active:false and stay off the screen. */
export function visibleDirectorSkills<T extends { active: boolean }>(skills: T[]): T[] {
  return skills.filter(skill => skill.active)
}
