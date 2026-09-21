"""Sandbox de execução do código gerado.

Dois lados que não se misturam. ``daemon.py`` é do processo do worker: verifica o acesso
ao daemon do Docker, que sobe o container. Todo o resto (motor de regras, asserções,
agregação, carga, harness, executor e envelope) é copiado para a imagem do sandbox
(``worker/sandbox/Dockerfile``) e roda dentro dela. ``harness.py`` e ``executor.py`` são os
únicos que executam código gerado, e o processo do worker nunca os importa.
"""
