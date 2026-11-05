"""Exceções compartilhadas entre backends, mesclagem e motor."""


class Cancelled(Exception):
    """O usuário cancelou a operação."""


class ExtractError(Exception):
    """Falha ao extrair um arquivo compactado (mensagem pronta para o usuário)."""


class WrongPassword(ExtractError):
    """A senha informada (ou a falta dela) não abre o arquivo."""


class UnsupportedFormat(ExtractError):
    """O backend não reconhece o formato do arquivo."""


class MissingTool(ExtractError):
    """Um programa externo necessário (7z, unar) não está instalado."""
