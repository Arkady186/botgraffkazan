"""
Главный файл запуска для веб-панели и VK бота
Запускает веб-сайт и VK бота одновременно
"""
import sys
import threading
import uvicorn

# Установка кодировки UTF-8 для вывода в консоль Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from config import WEB_HOST, WEB_PORT


def run_vk_bot():
    """Запуск VK бота в отдельном потоке"""
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    
    from vk_bot.main import main as vk_bot_main
    try:
        vk_bot_main()
    except Exception as e:
        print(f"\n❌ VK бот остановлен: {e}")


def main():
    """Запуск веб-панели и VK бота"""
    print("=" * 50)
    print("🎨  Учёт граффити · Казань (сайт + VK)")
    print("=" * 50)
    print()
    print(f"🌐 Веб-панель: http://{WEB_HOST}:{WEB_PORT}")
    print(f"🤖 VK Бот: запущен")
    print()
    print("Логины для веб-панели:")
    print("  admin / admin123")
    print("  operator / operator123")
    print()
    print("Нажмите Ctrl+C для остановки")
    print("=" * 50)

    # Запуск VK бота в отдельном потоке
    vk_thread = threading.Thread(target=run_vk_bot, daemon=True)
    vk_thread.start()

    # Запуск веб-сервера
    uvicorn.run("web.app:app", host=WEB_HOST, port=WEB_PORT, reload=False)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nОстановка...")
