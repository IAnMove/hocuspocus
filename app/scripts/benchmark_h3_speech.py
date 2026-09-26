"""Controlled 2x2x2 dialogue-tail experiment using the existing local API client.

The expanded dialogue is deliberately authored, not claimed as a successful
LLM Creative rewrite. This isolates how meaningful extra speech affects tails.
"""
from __future__ import annotations
import argparse
from pathlib import Path
from benchmark_h3 import PROMPT, request, run_row, save
from benchmark_h3_report import render

SCENE = ("integrated_multimodal_description: [Shot 1] Live-action Seinfeld sitcom in Jerry Seinfeld's "
         "1990s apartment. Fixed medium two-shot of George Costanza, played by Jason Alexander, "
         "wearing a beige cardigan over a light blue shirt, and Jerry Seinfeld wearing a gray sweater. "
         "George proudly holds an empty white coffee mug. Natural acting and dry comic timing. ")
GEORGE = 'George Costanza (S1) <d>[Spanish] He dejado el café para ahorrar</d>. '
JERRY = 'Jerry raises one eyebrow and replies: Jerry Seinfeld (S2) <d>[Spanish] Ahora solo te falta dejar de comprar tazas</d>. '
EXTRA = 'George points at the mug and adds: George Costanza (S1) <d>[Spanish] Estaba de oferta</d>. '
TAILS = {
    'action': 'George lowers the mug and Jerry folds his arms. They exchange a deadpan look for the final comic beat.',
    'silence': 'After the last line, both stop speaking, keep their mouths closed and exchange a silent deadpan look through the end.',
}
SOUNDS = {'ambient': 'Quiet apartment room tone and distant city traffic.', 'none': 'N/A'}


def prepare_matrix(root: Path):
    rows = []
    for style in ('faithful', 'creative'):
        for sound in SOUNDS:
            for tail, ending in TAILS.items():
                name = f'speech4-{style}-{sound}-{tail}'
                dialogue = GEORGE + (EXTRA if style == 'creative' else '') + JERRY
                prompt = SCENE + dialogue + ending + '\noverall_soundscape: ' + SOUNDS[sound] + '\nnon_diegetic_music: N/A'
                prompt_file = name + '-prompt.json'
                save(root / prompt_file, {'source_prompt': PROMPT, 'enhanced': prompt,
                    'authoring': 'Controlled benchmark script; Creative adds one explicitly authored line, not an LLM-generated claim.'})
                rows.append({'id': name, 'model': 'minimax_h3_fused_turbo', 'preset': '', 'attention': 'sla',
                    'steps': 4, 'frames': 243, 'profile': 3, 'style': style, 'audio': 'native',
                    'soundscape': sound, 'ending': tail, 'prompt_file': prompt_file,
                    'dialogue_extra': 'Estaba de oferta' if style == 'creative' else None})
    save(root / 'matrix.json', rows)
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--server-pid', required=True, type=int)
    args = parser.parse_args()
    rows = prepare_matrix(args.output_dir)
    page = Path(__file__).resolve().parents[1] / 'outputs/h3_benchmark/h3-speech-4step.html'
    # All requests use native duration preservation. "none" only changes the
    # authored soundscape, avoiding the legacy policy's shorter auto-duration.
    for row in rows:
        result = run_row(args.base_url, args.output_dir, row, server_pid=args.server_pid)
        folder = args.output_dir / row['id']
        save(folder / 'assessment.json', {'notes': (
            f"4 steps · {row['style']} · soundscape {row['soundscape']} · ending {row['ending']}. "
            + ('Dialogue extended by hand with «Estaba de oferta»; not attributed to the LLM. ' if row['style'] == 'creative' else 'Two original lines. ')
            + 'No long block of silence. Untrimmed audio; awaiting listening.')})
        render(args.output_dir, page)
        print('RESULT', row['id'], result.get('elapsed_seconds'), result.get('result', {}).get('status'), flush=True)
        if result.get('result', {}).get('status') not in ('completed', 'complete', 'done'):
            raise RuntimeError('Stopped batch after failed/unknown generation; inspect before resuming.')
    print('All eight speech variants complete.', flush=True)


if __name__ == '__main__':
    main()
