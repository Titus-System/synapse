"""Agrega anotações textuais explícitas; não interpreta áudio ou converte números."""
import csv
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVAL = ROOT / 'docs/avaliacoes'
FIXTURES = ROOT / 'api/src/test/resources/transcricao'


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def wer(expected, actual):
    reference = re.findall(r'[^\W_]+', expected.lower())
    hypothesis = re.findall(r'[^\W_]+', actual.lower())
    previous = list(range(len(hypothesis) + 1))
    for i, word in enumerate(reference, 1):
        current = [i]
        for j, other in enumerate(hypothesis, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j - 1] + (word != other)))
        previous = current
    return previous[-1], len(reference)


def percentile(values, fraction):
    return sorted(values)[math.ceil(len(values) * fraction) - 1]


def main():
    if '--historico' not in sys.argv:
        raise SystemExit('Anotacoes contestadas: use --historico apenas para auditoria, sem aprovar qualidade.')
    corpus = {p['id']: p for p in read(FIXTURES / 'corpus.json')['phrases']}
    manifest = {r['id']: r for r in read(FIXTURES / 'gravacoes.json')['recordings']}
    # Anotações revisadas textualmente nesta sessão; exige revisão independente.
    # IDs omitidos são erros segundo o critério documentado no relatório.
    correct = {
        'deepgram-nova3': {
            'voz-a': {'r01': 'loja marca cargo percentual', 'r02': 'percentual marca exclusao',
                      'r03': 'valor', 'r04': '', 'r05': '', 'r06': '', 'r07': '', 'r08': '',
                      'r10': 'loja marca cargo percentual', 'r11': 'valor excluida exclusao',
                      'r12': 'inicio fim marca loja percentual'},
            'voz-b': {'r01': 'loja marca percentual', 'r02': 'percentual marca exclusao',
                      'r03': 'valor', 'r04': 'exclusao', 'r05': 'inicio fim loja',
                      'r06': 'data valor', 'r07': 'marca1 marca2 limite_inferior limite_superior bonus',
                      'r08': 'limite_inferior limite_superior bonus',
                      'r10': 'loja marca cargo percentual', 'r11': 'valor excluida exclusao',
                      'r12': 'inicio fim marca loja percentual'}},
        'groq-whisper-large-v3': {
            'voz-a': {'r01': 'loja marca cargo', 'r02': 'percentual marca exclusao',
                      'r03': 'matricula valor', 'r04': '', 'r05': '', 'r06': '', 'r07': '', 'r08': '',
                      'r10': 'loja marca cargo percentual', 'r11': 'valor',
                      'r12': 'inicio fim marca loja percentual'},
            'voz-b': {'r01': 'loja marca cargo percentual', 'r02': 'percentual exclusao',
                      'r03': 'matricula valor', 'r04': 'exclusao', 'r05': 'inicio fim loja',
                      'r06': 'cargo valor', 'r07': 'marca1 marca2 limite_inferior limite_superior bonus',
                      'r08': 'limite_inferior limite_superior bonus',
                      'r10': 'loja marca cargo percentual', 'r11': 'valor',
                      'r12': 'inicio fim marca loja percentual'}}
    }
    sources = ['piloto-20261006-132246.json', 'piloto-groq-20261006-135904.json']
    annotations, metrics = [], {}
    suspect = {'voz-a-r04-ogg','voz-a-r05-ogg','voz-a-r06-ogg','voz-a-r07-ogg','voz-a-r08-ogg'}
    for source in sources:
        all_runs = read(EVAL / source)['runs']
        runs = [r for r in all_runs if r['candidate_id'] in correct and r['status'] == 'ok']
        provider = runs[0]['candidate_id']
        totals, successes = Counter(), Counter()
        subset_total, subset_success = Counter(), Counter()
        errors, words = 0, 0
        for run in runs:
            recording = manifest[run['recording_id']]
            assert recording['reading_verified'] is True
            phrase_id = recording['phrase_ids'][0]
            voice = recording['speaker_id']
            accepted = set(correct[provider][voice][phrase_id].split())
            elements = corpus[phrase_id]['elements']
            assert accepted <= {e['id'] for e in elements}
            for element in elements:
                ok = element['id'] in accepted
                totals[element['type']] += 1
                successes[element['type']] += ok
                if run['recording_id'] not in suspect:
                    subset_total[element['type']] += 1
                    subset_success[element['type']] += ok
                annotations.append({'candidate_id':provider,'recording_id':run['recording_id'],
                    'element_id':element['id'],'type':element['type'],'expected_value':element['value'],
                    'correct':ok,'evidence':run['text'],
                    'review_status':'historico_contestado'})
            e, w = wer(recording['expected_text'], run['text'])
            errors += e; words += w
        assert len(runs) == 22 and sum(totals.values()) == 78
        latency = [r['latency_ms'] for r in runs]
        metrics[provider] = {'speech_runs':len(runs),'correct':sum(successes.values()),'total':sum(totals.values()),
            'by_type':{t:{'correct':successes[t],'total':totals[t]} for t in sorted(totals)},
            'sensitivity_excluding_suspect_files':{'correct':sum(subset_success.values()),'total':sum(subset_total.values()),
                'by_type':{t:{'correct':subset_success[t],'total':subset_total[t]} for t in sorted(subset_total)}},
            'wer_errors':errors,'wer_words':words,'wer':errors/words,
            'latency_mean_ms':sum(latency)/len(latency),'latency_p50_ms':percentile(latency,.5),
            'latency_p95_ms':percentile(latency,.95)}
    payload={'status':'historico_contestado_nao_usar_para_decisao','final_acceptance':False,
             'sources':sources,'annotations':annotations,'metrics':metrics}
    (EVAL/'metricas-consolidadas.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    with (EVAL/'anotacoes-elementos.csv').open('w',encoding='utf-8-sig',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=list(annotations[0]));writer.writeheader();writer.writerows(annotations)
    print(json.dumps(metrics,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
