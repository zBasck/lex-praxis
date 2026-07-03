"""Popula o banco com usuários iniciais. SEM DADOS SINTÉTICOS.

Sistema operando exclusivamente com DJE/DJR (PJe Comunica) + OAB.
Nenhuma referencia a DataJud.

Apenas:
  - Cria o usuário admin (se não existir)
  - Cria o usuário advogado (opcional, sem processos)
  - Imprime instruções para começar a usar com dados reais
"""
from __future__ import annotations
import sys

from app import create_app
from app.core.extensions import db
from app.core.models import User, UserConfig, SystemConfig, OABMonitorada


def popular(force: bool = False):
    app = create_app()
    with app.app_context():
        admin = User.query.filter_by(email="admin@lexpraxis.local").first()
        if not admin:
            admin = User(
                name="Administrador",
                email="admin@lexpraxis.local",
                role="admin",
                active=True,
            )
            admin.set_password("1234")
            db.session.add(admin)
            db.session.commit()
            print("[OK] Usuário admin criado: admin@lexpraxis.local / 1234")
        else:
            print("[--] Usuário admin já existe.")

        demo = User.query.filter_by(email="advogado@lexpraxis.local").first()
        if not demo:
            demo = User(
                name="Dra. Renata Souza",
                email="advogado@lexpraxis.local",
                oab="SP 123.456",
                role="advogado",
                active=True,
            )
            demo.set_password("demo123")
            db.session.add(demo)
            db.session.commit()
            print("[OK] Usuário demo criado: advogado@lexpraxis.local / demo123")
        else:
            print("[--] Usuário demo já existe.")

        # Cria UserConfig padrao para todos os usuarios existentes
        for u in User.query.all():
            if not UserConfig.query.filter_by(user_id=u.id).first():
                db.session.add(UserConfig(user_id=u.id))
        db.session.commit()

        # Configuracoes globais defaults
        defaults = [
            ("HARVEST_INTERVAL_MINUTES", "120", "Intervalo do robo (min)"),
            ("OAB_MONITOR_INTERVAL_MINUTES", "60", "Intervalo do monitor de OAB"),
            ("DJE_DAYS_BACK_DEFAULT", "7", "Janela retroativa padrao (dias)"),
            ("DJE_MAX_DAYS_BACK", "365", "Janela maxima para historico"),
            ("IA_ENABLED", "0", "IA local habilitada (0/1)"),
            ("IA_PROVIDER", "local", "Provider de IA (local, ollama, openai_compat)"),
            ("IA_ENDPOINT", "http://localhost:11434", "Endpoint da IA local"),
            ("IA_MODEL", "llama3.1:8b", "Modelo de IA local"),
            ("DIAS_UTEIS_PADRAO", "5", "Dias uteis para prazos sem regra"),
            ("ADMIN_EMAIL", "admin@lexpraxis.local", "Email do admin principal"),
        ]
        for k, v, d in defaults:
            if not SystemConfig.query.get(k):
                db.session.add(SystemConfig(key=k, value=v, description=d))
        db.session.commit()

        print()
        print("=" * 60)
        print("Sistema pronto para uso com dados REAIS (DJE/DJR).")
        print("=" * 60)
        print()
        print("Próximos passos:")
        print("  1. Faça login em http://localhost:5000/login")
        print("     (admin@lexpraxis.local / 1234)")
        print("  2. Cadastre clientes em /clientes")
        print("  3. Cadastre sua OAB em /oabs (ex: 123456 + SP)")
        print("  4. Ative a coleta DJE/DJR no .env:")
        print("        DJE_COMUNICA_ENABLED=true")
        print("     (sem certificado, sem chave de API)")
        print("  5. Acesse /monitor-dje e clique em 'Executar agora'")
        print()
        print("Sem DJE_COMUNICA_ENABLED=true, o sistema nao inventara")
        print("publicacoes. Tudo que aparece vem do PJe Comunica.")
        print()
        print("Apos login, va em /configuracoes para configurar IA local,")
        print("preferencias, e demais opcoes do sistema.")
        print()
        print("O admin pode criar novos usuarios em /admin/usuarios")
        print("(requer login como admin).")


if __name__ == "__main__":
    force = "--force" in sys.argv
    popular(force=force)
