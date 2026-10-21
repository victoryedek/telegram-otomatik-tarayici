import os
import json
import hashlib
import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.messages import GetCommonChatsRequest
from telethon.errors import FloodWaitError
from datetime import datetime, timezone, timedelta

# ================= AYARLAR =================
api_id = int(os.environ.get("API_ID"))
api_hash = os.environ.get("API_HASH")
session_str = os.environ.get("SESSION_STRING")
HEDEF_GRUP_ID = int(os.environ.get("HEDEF_GRUP_ID"))

hedefler_str = os.environ.get("HEDEFLER_LISTESI", "")
HEDEFLER = [int(x.strip()) for x in hedefler_str.split(",") if x.strip()]

TARAMA_LIMITI = 100
TR_TIMEZONE = timezone(timedelta(hours=3))
# ===========================================

client = TelegramClient(StringSession(session_str), api_id, api_hash)
rapor_dosyasi = "rapor.txt"
islenenler_dosyasi = "islenen_mesajlar.json"

def sifrele(metin):
    """Public depoda grup ve mesaj ID'lerinin dışarıdan görünmemesi için SHA-256 ile gizler."""
    return hashlib.sha256(metin.encode("utf-8")).hexdigest()[:16]

def islenenleri_yukle():
    if os.path.exists(islenenler_dosyasi):
        try:
            with open(islenenler_dosyasi, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"mesajlar": [], "hedef_mesaj_idleri": []}
    return {"mesajlar": [], "hedef_mesaj_idleri": []}

def islenenleri_kaydet(veri):
    veri["mesajlar"] = veri["mesajlar"][-15000:]
    veri["hedef_mesaj_idleri"] = veri["hedef_mesaj_idleri"][-15000:]
    with open(islenenler_dosyasi, "w", encoding="utf-8") as f:
        json.dump(veri, f)

def rapora_yaz(metin):
    with open(rapor_dosyasi, "a", encoding="utf-8") as f:
        f.write(metin + "\n")

async def guvenli_ilet(message, baslik_bilgisi):
    """Mesajı forward etmeyi dener; grupta içerik koruması varsa indirip gönderir."""
    try:
        await message.forward_to(HEDEF_GRUP_ID)
        await asyncio.sleep(1.2)
    except FloodWaitError as e:
        print(f"Telegram hız sınırı: {e.seconds} saniye bekleniyor...")
        await asyncio.sleep(e.seconds + 2)
        await message.forward_to(HEDEF_GRUP_ID)
    except Exception:
        # İçerik korumalı gruplar için yedek gönderim (Fallback)
        try:
            if message.media:
                dosya = await message.download_media()
                await client.send_file(HEDEF_GRUP_ID, dosya, caption=f"{baslik_bilgisi}\n\n{message.text or ''}")
                if dosya and os.path.exists(dosya):
                    os.remove(dosya)
            else:
                await client.send_message(HEDEF_GRUP_ID, f"{baslik_bilgisi}\n\n{message.text or ''}")
            await asyncio.sleep(1.2)
        except Exception as err:
            print(f"Yedek gönderim hatası: {err}")

async def tara_ve_raporla():
    gecmis_veri = islenenleri_yukle()
    islenen_idler = set(gecmis_veri.get("mesajlar", []))
    hedef_mesaj_idleri = set(gecmis_veri.get("hedef_mesaj_idleri", []))

    su_an_tr = datetime.now(TR_TIMEZONE).strftime('%d/%m/%Y %H:%M')
    with open(rapor_dosyasi, "w", encoding="utf-8") as f:
        f.write(f"=== AKTİVİTE & YANIT RAPORU: {su_an_tr} (TSİ) ===\n\n")

    print(f">>> Tarama başladı... (TSİ: {su_an_tr})")
    yeni_mesaj_sayisi = 0

    # 1. Ortak grupları bul
    ortak_gruplar = {}
    for hedef_id in HEDEFLER:
        try:
            hedef_user = await client.get_input_entity(hedef_id)
            res = await client(GetCommonChatsRequest(user_id=hedef_user, max_id=0, limit=100))
            for chat in res.chats:
                if chat.id != abs(HEDEF_GRUP_ID) and chat.id != HEDEF_GRUP_ID:
                    ortak_gruplar[chat.id] = chat
        except Exception as e:
            print(f"Ortak grup sorgu uyarısı: {e}")

    print(f"Toplam {len(ortak_gruplar)} adet ortak grup incelenecek.")

    # 2. Grupları tara
    for chat_id, chat in ortak_gruplar.items():
        chat_title = getattr(chat, 'title', 'Grup')
        
        try:
            grup_basligi_yazildi = False
            
            mesajlar_listesi = []
            async for m in client.iter_messages(chat, limit=TARAMA_LIMITI):
                mesajlar_listesi.append(m)
            mesajlar_listesi.reverse()

            for message in mesajlar_listesi:
                ham_id = f"{chat.id}_{message.id}"
                gizli_id = sifrele(ham_id)
                
                hedef_mesaji_mi = (message.sender_id in HEDEFLER)
                yanit_mi = False

                if hedef_mesaji_mi:
                    hedef_mesaj_idleri.add(gizli_id)
                    hedef_mesaj_idleri.add(ham_id)

                # Yanıt kontrolü
                if message.reply_to and message.reply_to.reply_to_msg_id:
                    yanit_ham_id = f"{chat.id}_{message.reply_to.reply_to_msg_id}"
                    yanit_gizli_id = sifrele(yanit_ham_id)
                    
                    if (yanit_gizli_id in hedef_mesaj_idleri) or (yanit_ham_id in hedef_mesaj_idleri):
                        yanit_mi = True
                    else:
                        try:
                            asil_mesaj = await client.get_messages(chat, ids=message.reply_to.reply_to_msg_id)
                            if asil_mesaj and asil_mesaj.sender_id in HEDEFLER:
                                yanit_mi = True
                                hedef_mesaj_idleri.add(yanit_gizli_id)
                        except Exception:
                            pass

                # Hem eski şifresiz hem yeni şifreli ID kontrolü
                if (gizli_id in islenen_idler) or (ham_id in islenen_idler):
                    continue

                if hedef_mesaji_mi or yanit_mi:
                    if not grup_basligi_yazildi:
                        rapora_yaz(f"\n📂 ORTAK GRUP: {chat_title}\n" + "-"*30)
                        grup_basligi_yazildi = True

                    chat_id_str = str(chat.id).replace("-100", "")
                    link = f"https://t.me/c/{chat_id_str}/{message.id}"
                    
                    tur = "Yazı/Mesaj"
                    if message.photo: tur = "FOTOĞRAF 📸"
                    elif message.video: tur = "VİDEO 🎥"
                    elif message.voice: tur = "SES 🎤"
                    elif message.document: tur = "DOSYA 📁"
                    
                    mesaj_tarihi_tr = message.date.astimezone(TR_TIMEZONE)
                    tarih_str = mesaj_tarihi_tr.strftime("%d/%m/%Y %H:%M")
                    
                    sender = await message.get_sender()
                    sender_name = getattr(sender, 'first_name', str(message.sender_id))
                    icerik = (message.text[:80] + '..') if message.text else ""
                    
                    etiket = "💬 [YANIT]" if yanit_mi else "👤 [HEDEF PAYLAŞIMI]"
                    detay_satiri = f"{etiket}\n[{tarih_str}] Gönderen: {sender_name} ({message.sender_id})\nTür: {tur}\nİçerik: {icerik}\nLink: {link}\n"
                    rapora_yaz(detay_satiri)
                    
                    await guvenli_ilet(message, f"{etiket} | {chat_title} | {sender_name}")
                    
                    yeni_mesaj_sayisi += 1
                    islenen_idler.add(gizli_id)

        except Exception as e:
            print(f"Grup işleme hatası: {e}")

    gecmis_veri["mesajlar"] = list(islenen_idler)
    gecmis_veri["hedef_mesaj_idleri"] = list(hedef_mesaj_idleri)
    islenenleri_kaydet(gecmis_veri)

    if yeni_mesaj_sayisi > 0:
        rapora_yaz(f"\n✅ Tarama bitti. Toplam {yeni_mesaj_sayisi} yeni öğe aktarıldı.")
        if os.path.exists(rapor_dosyasi):
            try:
                await client.send_file(
                    HEDEF_GRUP_ID, 
                    rapor_dosyasi, 
                    caption=f"🔔 **Aktivite Raporu ({su_an_tr})**\nToplam {yeni_mesaj_sayisi} yeni mesaj/yanıt iletildi."
                )
            except Exception as e:
                print(f"Rapor gönderme hatası: {e}")
    else:
        print("Yeni içerik bulunamadı.")

async def main():
    await tara_ve_raporla()

if __name__ == '__main__':
    with client:
        client.loop.run_until_complete(main())
