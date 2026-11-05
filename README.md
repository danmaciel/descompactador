# Descompactador

Extrai vários arquivos compactados **de uma vez, na mesma pasta**, juntando as pastas que
tiverem o mesmo nome.

Exemplo: `fotos-parte1.zip` e `fotos-parte2.zip` contêm, cada um, uma pasta `Fotos/`. Em vez
de duas pastas separadas, você fica com uma só `Fotos/` com o conteúdo dos dois. Se
`Fotos/` já existir no destino, os arquivos novos são adicionados a ela.

É útil para exportações do Google Takeout, backups e downloads divididos em várias partes.

---

## Sumário

1. [Instalação](#1-instalação)
2. [Formas de abrir o app](#2-formas-de-abrir-o-app)
3. [Passo a passo](#3-passo-a-passo)
4. [A janela, item por item](#4-a-janela-item-por-item)
5. [Quando um arquivo já existe no destino](#5-quando-um-arquivo-já-existe-no-destino)
6. [Arquivos com senha](#6-arquivos-com-senha)
7. [Arquivos divididos em partes (multivolume)](#7-arquivos-divididos-em-partes-multivolume)
8. [Formatos suportados](#8-formatos-suportados)
9. [Dúvidas comuns e problemas](#9-dúvidas-comuns-e-problemas)
10. [Desinstalar](#10-desinstalar)
11. [Para desenvolvedores](#11-para-desenvolvedores)

---

## 1. Instalação

### Requisitos

| Programa | Para quê | Como verificar |
|---|---|---|
| Python 3 com PySide6 | a janela | `/usr/bin/python3 -c "import PySide6"` |
| `7z` (pacote `7zip`) | zip, 7z, iso e outros | `7z i` |
| `unar` | RAR | `unar -v` |

No Aurora/Kinoite os três já vêm instalados.

### Instalando

Na pasta do projeto, rode:

```sh
cd ~/projetos/descompactador
./install.sh
```

Nada é instalado no sistema: tudo fica na sua pasta pessoal. O script cria três coisas:

| Arquivo criado | O que faz |
|---|---|
| `~/.local/bin/descompactador` | o comando para abrir o app |
| `~/.local/share/kio/servicemenus/descompactador.desktop` | a opção **Extrair todos juntos...** no Dolphin |
| `~/.local/share/applications/descompactador.desktop` | o atalho no menu de aplicativos |

> **Importante:** o app roda direto desta pasta do projeto. Se você mover ou renomear a pasta,
> rode o `./install.sh` de novo.

---

## 2. Formas de abrir o app

### Pelo Dolphin (o jeito mais prático)

1. Selecione os arquivos compactados (use Ctrl ou Shift para selecionar vários).
2. Clique com o botão direito e escolha **Extrair todos juntos...**.

A janela abre com os arquivos já listados.

### Pelo menu de aplicativos

Procure **Descompactador** no menu. A janela abre vazia e você adiciona os arquivos.

### Pelo terminal

```sh
descompactador ~/Downloads/takeout-*.zip
```

Sem instalar, de dentro da pasta do projeto:

```sh
/usr/bin/python3 -m descompactador arquivo1.zip arquivo2.rar ...
```

---

## 3. Passo a passo

1. **Adicione os arquivos.** Use o Dolphin, o botão **Adicionar…** ou arraste os arquivos para a janela.
2. **Confira o destino.** Ele começa preenchido com a pasta do primeiro arquivo. Para mudar,
   clique em **Escolher…** ou digite o caminho. Se a pasta não existir, o app pergunta se deve criá-la.
3. **Escolha o que fazer com arquivos repetidos.** O padrão, **Perguntar**, mostra uma janela a
   cada conflito. Veja a [seção 5](#5-quando-um-arquivo-já-existe-no-destino).
4. Clique em **Extrair**.
5. Responda às perguntas que aparecerem (conflitos e senhas).
6. No fim, um resumo mostra quantos arquivos foram extraídos, renomeados, sobrescritos e assim por diante.

> **Dica:** o conteúdo de cada arquivo vai **direto** para o destino, sem criar uma subpasta com o
> nome do arquivo compactado. Se um `.zip` tiver arquivos soltos na raiz, eles caem soltos no
> destino. Se o destino for a pasta Downloads, isso pode bagunçá-la. Nesse caso, escolha ou
> digite uma pasta própria, como `~/Downloads/Takeout`.

---

## 4. A janela, item por item

```
┌──────────────────────────────────────────────────────────────────────┐
│ Arquivo                         Tamanho    Situação                  │
│ takeout-001.zip                 2,0 GB     OK: 1532 novo(s)          │
│ takeout-002.zip                 2,0 GB     Extraindo 45%             │
│ backup.part1.rar (+3 volumes)   4,1 GB     Aguardando                │
├──────────────────────────────────────────────────────────────────────┤
│ [Adicionar…] [Remover] [Limpar]            Arraste arquivos para cá  │
│ Destino: [/home/voce/Downloads/Takeout              ] [Escolher…]    │
│ Se um arquivo já existir: [Perguntar ▾]                              │
│ [██████████████░░░░░░░░░░░░░░░░░░░░░░]                               │
│ Extraindo takeout-002.zip (2 de 3)                                   │
│ [▸ Detalhes]                                     [Extrair] [Fechar]  │
└──────────────────────────────────────────────────────────────────────┘
```

| Elemento | Função |
|---|---|
| **Lista** | um item por arquivo compactado. Um arquivo dividido em partes ocupa um item só, e o tamanho é a soma das partes. Passe o mouse sobre o nome para ver os caminhos de todas as partes. |
| **Adicionar…** | abre o seletor de arquivos (aceita vários de uma vez) |
| **Remover** | tira da lista os itens selecionados (Ctrl/Shift para vários) |
| **Limpar** | esvazia a lista |
| **Destino** | a pasta onde tudo será extraído e mesclado |
| **Se um arquivo já existir** | o que fazer quando um arquivo já existe no destino ([seção 5](#5-quando-um-arquivo-já-existe-no-destino)) |
| **Barra de progresso** | o progresso geral do lote |
| **Detalhes** | mostra ou esconde o registro: qual programa foi usado em cada arquivo, avisos, e cada item sobrescrito, renomeado ou pulado |
| **Extrair / Cancelar** | durante a extração, o botão **Extrair** vira **Cancelar** |
| **Fechar** | fecha a janela. Se houver uma extração em andamento, pede confirmação antes. |

### O que aparece na coluna "Situação"

| Situação | Significado |
|---|---|
| Aguardando | ainda não foi processado |
| Analisando… | identificando o formato e verificando se tem senha |
| Extraindo NN% | extraindo |
| Mesclando… | movendo o conteúdo extraído para o destino |
| **OK:** N novo(s), … | concluído. Mostra quantos itens são novos, sobrescritos, renomeados, pulados e idênticos. |
| **Erro:** … | falhou. O motivo aparece na própria coluna. |
| Pulado (sem senha) | você escolheu pular este arquivo no pedido de senha |
| Cancelado | a extração foi cancelada antes de terminar este arquivo |
| Volume inicial ausente | só há partes do meio de um arquivo dividido ([seção 7](#7-arquivos-divididos-em-partes-multivolume)) |

Clicar em **Extrair** de novo processa a lista inteira outra vez. Isso é seguro: arquivos
idênticos aos que já estão no destino são ignorados sem perguntar.

---

## 5. Quando um arquivo já existe no destino

**Pastas** com o mesmo nome são sempre **mescladas**: o conteúdo novo é colocado dentro da pasta
que já existe. Só há conflito quando um **arquivo** com o mesmo caminho já existe.

**Arquivos idênticos** (mesmo tamanho e mesmo conteúdo) são ignorados em silêncio e aparecem
como "idêntico(s)" no resumo.

### A janela de conflito

Com **Perguntar** selecionado, cada conflito abre esta janela:

```
┌────────────────────────────────────────────────────────────────────────┐
│ Fotos/capa.jpg já existe no destino.                                   │
│ Existente:          1,2 MB, modificado em 10/03/2024 14:02:11          │
│ Novo (de b.zip):    1,3 MB, modificado em 15/03/2024 09:30:00 (mais novo)│
│ [ ] Aplicar a todos os conflitos restantes                             │
│ [Sobrescrever] [Manter o mais novo] [Renomear] [Pular]  [Cancelar tudo]│
└────────────────────────────────────────────────────────────────────────┘
```

| Botão | Resultado |
|---|---|
| **Sobrescrever** | o arquivo novo substitui o existente |
| **Manter o mais novo** | compara as datas de modificação e fica com o mais recente |
| **Renomear** | guarda os dois: o novo vira `capa (1).jpg`, depois `capa (2).jpg`, e assim por diante. É o botão padrão (tecla Enter). |
| **Pular** | mantém o existente e descarta o novo |
| **Cancelar tudo** | interrompe o lote (Esc tem o mesmo efeito). O que já foi extraído continua no destino. |

Marque **Aplicar a todos os conflitos restantes** para repetir a escolha em todos os conflitos
seguintes do lote, inclusive os dos próximos arquivos compactados.

### Escolher a regra antes de começar

No campo **Se um arquivo já existir**, você pode fixar a regra para o lote inteiro. Assim
nenhuma janela de conflito aparece:

- Perguntar (padrão)
- Sobrescrever
- Manter o mais novo
- Renomear o novo
- Pular o novo

### Pasta contra arquivo

Às vezes um lado é pasta e o outro é arquivo, como uma pasta `notas` no destino e um arquivo
`notas` no compactado. Nesse caso, o app **nunca apaga a pasta**: só é possível **Renomear**
ou **Pular** o item novo, e os outros botões ficam desativados. Uma pasta renomeada mantém o
nome inteiro: `Album.2024 (1)`.

---

## 6. Arquivos com senha

Antes de extrair, o app verifica se o arquivo é protegido. Se for, pede a senha:

- **Extrair**: tenta com a senha digitada. Marque **Mostrar senha** para conferir o que digitou.
- **Pular este arquivo**: segue para o próximo item da lista. Este fica como "Pulado (sem senha)".
- **Cancelar tudo**: interrompe o lote.

Se a senha estiver errada, a janela aparece de novo com o aviso **"Senha incorreta. Tente
novamente."** Nada pela metade fica no destino.

**Senhas reaproveitadas:** quando uma senha funciona, o app a tenta primeiro nos próximos arquivos
protegidos. Em partes de um mesmo backup com a mesma senha, você só digita uma vez. As senhas
ficam **só na memória** e somem quando você fecha o app; nada é gravado em disco.

---

## 7. Arquivos divididos em partes (multivolume)

O app reconhece estes padrões de nome e trata cada conjunto como **um único arquivo**:

| Padrão | Exemplo | Por onde começa |
|---|---|---|
| RAR novo | `filme.part1.rar`, `filme.part2.rar`, … | `part1` (ou `part01`) |
| RAR antigo | `filme.rar`, `filme.r00`, `filme.r01`, … | `filme.rar` |
| Numerado | `backup.7z.001`, `backup.7z.002`, … | `.001` |
| ZIP dividido | `dados.zip`, `dados.z01`, `dados.z02`, … | `dados.zip` |

- Você pode selecionar **qualquer parte, ou todas**: o resultado é um item só na lista, como
  "filme.part1.rar (+3 volumes)".
- Todas as partes precisam estar **na mesma pasta**.
- Se a parte inicial estiver faltando, o item aparece como **"Volume inicial ausente"** e é
  ignorado. Os outros itens da lista são extraídos normalmente.
- Se faltar uma parte do meio, o item termina com **Erro**, e o motivo aparece na coluna Situação.

---

## 8. Formatos suportados

| Formato | Extensões | Extraído por |
|---|---|---|
| ZIP | `.zip`, `.z01`… | `7z` |
| 7-Zip | `.7z`, `.7z.001`… | `7z` |
| RAR | `.rar`, `.partN.rar`, `.r00`… | `unar` |
| TAR | `.tar`, `.tar.gz`/`.tgz`, `.tar.bz2`/`.tbz2`, `.tar.xz`/`.txz`, `.tar.zst`/`.tzst` | o próprio Python |
| Arquivo único comprimido | `.gz`, `.bz2`, `.xz`, `.zst`, `.lzma` | `7z` |
| Outros | `.iso`, `.cab` e o que mais o `7z` abrir | `7z` |

Se o `7z` não reconhecer um arquivo, o app tenta com o `unar` automaticamente.

---

## 9. Dúvidas comuns e problemas

**A opção "Extrair todos juntos..." não aparece no Dolphin.**
Feche todas as janelas do Dolphin e abra de novo. Se não resolver:

```sh
chmod +x ~/.local/share/kio/servicemenus/descompactador.desktop
kbuildsycoca6
```

Verifique também se o arquivo selecionado é de um formato da [seção 8](#8-formatos-suportados).
Partes como `.z01` não mostram a opção: selecione o `.zip` principal.

**Aparece "Para extrair RAR, instale o pacote 'unar'".**
O `7z` do Fedora não abre RAR. Instale o `unar`.

**Apareceu uma pasta `.descompactador-xxxx` no destino.**
É a área temporária usada durante a extração, e o app a apaga sozinho ao terminar. Ela só
sobra se o app foi encerrado à força (travamento, `kill`, desligamento). Nesse caso, pode
apagá-la.

**Posso extrair de novo para o mesmo lugar?**
Pode. Arquivos idênticos são ignorados sem perguntar. Só aparecem conflitos de arquivos que de
fato mudaram.

**Cancelei no meio. O que acontece?**
O arquivo que estava sendo extraído é descartado por inteiro, sem sobras pela metade. Os
arquivos que já tinham terminado continuam no destino, e os que faltavam aparecem como "Cancelado".

**Quero ver o que foi sobrescrito ou renomeado.**
Abra **Detalhes** no canto inferior esquerdo. O registro lista cada item afetado.

**Erro de permissão no destino.**
Escolha uma pasta onde você tenha permissão de escrita, como qualquer pasta dentro da sua pasta pessoal.

---

## 10. Desinstalar

```sh
cd ~/projetos/descompactador
./uninstall.sh
```

Remove o comando, a opção do Dolphin e o atalho do menu. A pasta do projeto continua onde está.

---

## 11. Para desenvolvedores

### Testes

```sh
/usr/bin/python3 -m unittest -v
```

- Os testes geram os arquivos compactados na hora, com `7z`, `zip` e `tarfile`.
- O teste da janela roda sem tela (`QT_QPA_PLATFORM=offscreen`).
- Não há teste automático de RAR, porque criar `.rar` exige o programa proprietário `rar`.

### Como funciona por dentro

Para cada arquivo da lista, o app:

1. escolhe o programa (tarfile, `7z` ou `unar`) e verifica se precisa de senha;
2. extrai numa pasta temporária oculta **dentro do destino**;
3. move o conteúdo para o destino, mesclando pastas e resolvendo conflitos. Como fica tudo no
   mesmo disco, mover é instantâneo (`rename`) e não ocupa espaço em dobro;
4. apaga a pasta temporária, mesmo em caso de erro ou cancelamento.

Proteções:
- symlinks no destino nunca são seguidos;
- itens perigosos em arquivos tar (`../`, caminhos absolutos) são ignorados e registrados em **Detalhes**.

| Módulo | Papel |
|---|---|
| `descompactador/volumes.py` | agrupa volumes e acha o volume inicial |
| `descompactador/backends.py` | tarfile / 7z / unar: detectar senha, extrair, progresso |
| `descompactador/merge.py` | mescla a pasta temporária no destino e resolve conflitos |
| `descompactador/engine.py` | orquestra tudo (sem Qt, testável) |
| `descompactador/gui/` | janela, diálogos e a thread de trabalho |
