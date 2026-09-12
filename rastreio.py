"""Medidas de um trecho de video para o enquadramento automatico.

Tres coisas, numa passada so de decodificacao:
  - onde estao os rostos, quadro a quadro (YuNet);
  - quanto a BOCA de cada rosto se mexe entre quadros vizinhos, que e o sinal de quem fala;
  - onde a camera da origem troca de plano (corte de cena), com a precisao do quadro.

Fica fora do app.py para rodar sem Flask: o mesmo codigo e exercitado localmente contra video de
verdade antes de ir para o Railway.

POR QUE ATIVIDADE DE BOCA. O detector acha rosto, nao locutor. Com duas pessoas no plano, a regra
era seguir o maior rosto, e a camera ficava presa em quem estava mais perto da lente enquanto a
outra pessoa falava. A boca de quem fala muda de forma entre quadros proximos; a de quem escuta,
quase nao. A medida desconta o quanto a regiao dos OLHOS do mesmo rosto mudou, para que balancar a
cabeca, piscar a luz ou recomprimir o quadro nao conte como fala.

A decisao de quem enquadrar NAO mora aqui: o worker so mede. A decisao fica no edge, em
_shared/enquadramento.ts, que tem teste.

POR QUE CORTE DE CENA AQUI. Sem ele o edge deduz a troca de plano pelo salto do rosto entre
amostras, o que localiza o corte com a precisao da amostragem. Por esse intervalo o recorte
mostrava o plano novo com o enquadramento do anterior.
"""
import glob
import os
import re
import subprocess
import tempfile
import threading
import time

import cv2
import numpy as np

YUNET_MODELO = os.environ.get('YUNET_MODEL', '/app/face_detection_yunet.onnx')

# Um detector por THREAD. O gunicorn roda com gthread (2 threads por worker), e o FaceDetectorYN
# guarda o tamanho de entrada como estado: a mesma instancia em duas requisicoes simultaneas troca
# o tamanho no meio da deteccao da outra.
_local = threading.local()

# Pontuacao de cena do ffmpeg (0 a 1) acima da qual o quadro e troca de plano.
#
# 0,2 e nao 0,3. Medido num podcast real (Flavio Augusto, 2 cortes, 111 s): as trocas de camera
# marcaram 0,289 / 0,338 / 0,360 / 0,395 / 0,423 / 0,432 / 0,459, e nenhum quadro sem troca passou
# de 0,115. Com 0,3 a troca de 0,289 (close escuro para plano aberto escuro) passava batida. O edge
# ainda cruza com o salto do rosto, mas corte acusado aqui tem a precisao do quadro.
LIMIAR_CENA = 0.2
# Teto de quadros amostrados por trecho. Acima disso a taxa cai para caber.
MAXIMO_QUADROS = 900

TAMANHO_BOCA = (32, 20)
TAMANHO_OLHOS = (32, 12)


class FalhaDeMedida(RuntimeError):
    """O trecho nao pode ser medido (ffmpeg falhou, video sem quadro)."""


def detector(largura, altura):
    det = getattr(_local, 'detector', None)
    if det is None:
        if not os.path.isfile(YUNET_MODELO):
            raise RuntimeError(
                'modelo do detector de rosto ausente em %s (o build deveria ter baixado)' % YUNET_MODELO
            )
        det = cv2.FaceDetectorYN.create(
            YUNET_MODELO, '', (largura, altura),
            score_threshold=0.6,   # abaixo disso e quase sempre textura de fundo
            nms_threshold=0.3,
            top_k=20,
        )
        _local.detector = det
    det.setInputSize((largura, altura))
    return det


def _regiao(cinza, x0, y0, x1, y1, tamanho):
    """Recorte normalizado (media zero, desvio unitario): imune a brilho e contraste."""
    alt, larg = cinza.shape[:2]
    x0 = int(max(0, round(x0)))
    y0 = int(max(0, round(y0)))
    x1 = int(min(larg, round(x1)))
    y1 = int(min(alt, round(y1)))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    r = cv2.resize(cinza[y0:y1, x0:x1], tamanho, interpolation=cv2.INTER_AREA).astype(np.float32)
    return (r - r.mean()) / (r.std() + 8.0)


def _regioes_do_rosto(cinza, f):
    """Boca e olhos de um rosto do YuNet: [x, y, w, h, olho_d(2), olho_e(2), nariz(2), boca_d(2), boca_e(2), score]."""
    x, y, w, h = (float(v) for v in f[0:4])
    boca_d = (float(f[10]), float(f[11]))
    boca_e = (float(f[12]), float(f[13]))
    olhos_y = (float(f[5]) + float(f[7])) / 2.0

    mx0 = min(boca_d[0], boca_e[0])
    mx1 = max(boca_d[0], boca_e[0])
    mw = max(mx1 - mx0, 0.25 * w)
    my = (boca_d[1] + boca_e[1]) / 2.0
    # Mais area ABAIXO dos cantos da boca: e o queixo que desce quando a boca abre.
    boca = _regiao(cinza, mx0 - 0.3 * mw, my - 0.12 * h, mx1 + 0.3 * mw, my + 0.22 * h, TAMANHO_BOCA)
    olhos = _regiao(cinza, x + 0.1 * w, olhos_y - 0.14 * h, x + 0.9 * w, olhos_y + 0.08 * h, TAMANHO_OLHOS)
    return boca, olhos


def _par_anterior(anteriores, cx, cy, w):
    """O mesmo rosto no quadro anterior: centro perto e tamanho parecido."""
    melhor = None
    melhor_d = None
    for a in anteriores:
        razao = a['w'] / w if w > 0 else 0
        d = ((a['cx'] - cx) ** 2 + (a['cy'] - cy) ** 2) ** 0.5
        if d <= 0.5 * w and 0.67 <= razao <= 1.5 and (melhor_d is None or d < melhor_d):
            melhor, melhor_d = a, d
    return melhor


def _ler_cortes(caminho):
    cortes = []
    if not os.path.isfile(caminho):
        return cortes
    with open(caminho, encoding='utf-8', errors='ignore') as fh:
        for linha in fh:
            m = re.search(r'pts_time:([0-9.]+)', linha)
            if m:
                cortes.append(round(float(m.group(1)), 3))
    return cortes


def medir_trecho(url, inicio, duracao, fps=5.0, largura=640, limiar_cena=LIMIAR_CENA):
    """Rostos, atividade de boca e cortes de cena de um trecho.

    Tempo sempre RELATIVO ao inicio do trecho. O tempo de cada amostra e DERIVADO do indice do
    quadro (t = i / fps), e nao casado contra uma lista pedida: o /extract-frames antigo casava, e
    errava (medido em 2026-08-26).
    """
    duracao = float(duracao)
    fps = max(0.2, min(8.0, float(fps)))
    fps = min(fps, MAXIMO_QUADROS / max(duracao, 0.1))
    largura = max(320, min(1280, int(largura)))
    t0 = time.time()

    with tempfile.TemporaryDirectory() as tmp:
        # Um decode, dois ramos: um amostra quadros para o detector, o outro mede troca de cena na
        # taxa cheia e em baixa resolucao (a pontuacao de cena nao precisa de detalhe).
        grafo = (
            '[0:v]split=2[amostra][cena];'
            '[amostra]fps=%.6f,scale=%d:-2[quadros];'
            '[cena]scale=160:-2,select=gt(scene\\,%.3f),metadata=mode=print:file=cenas.txt,nullsink'
        ) % (fps, largura, limiar_cena)
        cmd = [
            'ffmpeg', '-hide_banner', '-loglevel', 'error',
            '-ss', '%.3f' % float(inicio), '-t', '%.3f' % duracao, '-i', url,
            '-an', '-filter_complex', grafo, '-map', '[quadros]',
            '-q:v', '4', '-frames:v', str(MAXIMO_QUADROS),
            '-f', 'image2', 'f_%06d.jpg', '-y',
        ]
        # UMA segunda tentativa quando nao veio quadro nenhum.
        #
        # POR QUE. Lendo o video por URL assinada, uma falha passageira de rede deixa o ffmpeg sem
        # decodificar nada, e o erro que sai e `-22 (Invalid argument)` do encoder mjpeg, que nao
        # parece erro de leitura. Medido em producao em 2026-09-11: de cinco cortes do mesmo video,
        # quatro mediram e um falhou assim. O preco desse tropeco e alto, porque quem chama
        # entende "worker sem detector" e cai no caminho de visao: aquele corte ficou com 48
        # pontos num plano so, ou seja, sem nenhum corte de camera.
        #
        # Duas tentativas, e nao cinco: se a segunda tambem nao traz quadro, o problema nao e
        # passageiro (trecho fora do arquivo, URL expirada, video ilegivel) e insistir so atrasa.
        arquivos: list[str] = []
        for tentativa in (1, 2):
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=tmp)
            arquivos = sorted(glob.glob(os.path.join(tmp, 'f_*.jpg')))
            if r.returncode == 0 and arquivos:
                break
            if tentativa == 1:
                logger.warning(
                    '[track-faces] tentativa 1 sem quadro (rc=%s): %s. Repetindo uma vez.',
                    r.returncode, (r.stderr or '')[-200:],
                )
                for f in arquivos:
                    try:
                        os.remove(f)
                    except OSError:
                        pass
                arquivos = []
                time.sleep(1.0)
                continue
            if r.returncode != 0:
                raise FalhaDeMedida('ffmpeg rc=%s %s' % (r.returncode, (r.stderr or '')[-300:]))
            raise FalhaDeMedida('nenhum quadro extraido')
        cortes = [c for c in _ler_cortes(os.path.join(tmp, 'cenas.txt')) if 0.05 < c < duracao - 0.05]

        amostras = []
        com_rosto = 0
        anteriores = []
        larg = alt = None
        det = None

        for i, caminho in enumerate(arquivos):
            img = cv2.imread(caminho)
            if img is None:
                continue
            hh, ww = img.shape[:2]
            if det is None or (ww, hh) != (larg, alt):
                det = detector(ww, hh)
                larg, alt = ww, hh

            t = round(i / fps, 3)
            t_anterior = (i - 1) / fps
            # Atravessando um corte de cena, o "mesmo lugar" do quadro e outra pessoa: nao compara.
            if any(t_anterior < c <= t for c in cortes):
                anteriores = []

            _, achados = det.detect(img)
            cinza = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            rostos = []
            atuais = []
            if achados is not None:
                for f in achados:
                    x, y, w, h = (float(v) for v in f[0:4])
                    cx, cy = x + w / 2.0, y + h / 2.0
                    boca, olhos = _regioes_do_rosto(cinza, f)
                    rosto = {
                        'xPct': round(100.0 * cx / ww, 2),
                        'yPct': round(100.0 * cy / hh, 2),
                        'wPct': round(100.0 * w / ww, 2),
                        'hPct': round(100.0 * h / hh, 2),
                        'score': round(float(f[14]), 3),
                    }
                    par = _par_anterior(anteriores, cx, cy, w)
                    if (par is not None and boca is not None and olhos is not None
                            and par['boca'] is not None and par['olhos'] is not None):
                        d_boca = float(np.mean(np.abs(boca - par['boca'])))
                        d_olhos = float(np.mean(np.abs(olhos - par['olhos'])))
                        rosto['fala'] = round(max(0.0, d_boca - d_olhos), 3)
                    atuais.append({'cx': cx, 'cy': cy, 'w': w, 'boca': boca, 'olhos': olhos})
                    rostos.append(rosto)
            anteriores = atuais
            if rostos:
                com_rosto += 1
            amostras.append({'t': t, 'faces': rostos})

    return {
        'fps': fps,
        'frameWidth': larg,
        'frameHeight': alt,
        'samples': amostras,
        'withFace': com_rosto,
        'cuts': cortes,
        'ms': int((time.time() - t0) * 1000),
    }
