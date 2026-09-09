"""One-time online preparation of the optional in-process CPU model."""
import os
from pathlib import Path
import subprocess
import sys


def main():
    from stenograph.config import Settings, data_root
    from stenograph.runtime_guard import RuntimeGuard
    folder = data_root()
    guard = RuntimeGuard(folder)
    if not guard.acquire():
        raise RuntimeError('Закройте СтеноГраф через меню трея и дождитесь окончания обновлений.')
    try:
        print('Устанавливаю готовый CPU-пакет llama-cpp-python. Требуется интернет.', flush=True)
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--only-binary=:all:',
                        'llama-cpp-python>=0.3.16,<0.4', '--extra-index-url',
                        'https://abetlen.github.io/llama-cpp-python/whl/cpu'], check=True)
        os.environ.pop('HF_HUB_OFFLINE', None)
        from huggingface_hub import hf_hub_download
        target = folder / 'models' / 'qwen2.5-1.5b'
        print('Загружаю Qwen2.5 1.5B Instruct Q4_K_M (~1.12 ГБ). Окно не закрывайте.', flush=True)
        path = hf_hub_download('Qwen/Qwen2.5-1.5B-Instruct-GGUF',
                               'qwen2.5-1.5b-instruct-q4_k_m.gguf', local_dir=target)
        from stenograph.intelligence import EmbeddedLLM
        settings = Settings.load(folder)
        model = EmbeddedLLM(path, settings.cpu_threads)
        try:
            model.check()
        finally:
            model.close()
        settings.llm_backend = 'embedded'
        settings.gguf_path = str(Path(path).resolve())
        settings.save(folder)
        print('ГОТОВО. Откройте Запустить.cmd. Протоколы работают без Ollama и без интернета.')
    finally:
        guard.release()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('Подготовка встроенной модели не завершена:', exc)
        print('Если готового пакета нет для вашего Python, используйте Ollama или Python 3.12 x64.')
        raise SystemExit(1)
