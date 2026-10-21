import os
import json
import base64
import hashlib
import asyncio
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.messages import GetCommonChatsRequest
from telethon.tl.functions.users import GetFullUserRequest
from telethon.errors import FloodWaitError
from datetime import datetime, timezone, timedelta

# ================= AYARLAR =================
api_id = int(os.environ.get("API_ID"))
api_hash = os.environ.get("API_HASH")
session_str = os.environ.get("SESSION_STRING")
HEDEF_GRUP_ID = int(os.environ.get("HEDEF_GRUP_ID"))

hedefler_str = os.environ.get("HEDEFLER_LISTESI", "")
VARSAYILAN_HEDEFLER = [int(x.strip()) for x in hedefler_str.split(",") if x.strip()]

TARAMA_LIMITI = 100
TR_TIMEZONE = timezone(timedelta(hours=3))
# ===========================================

client = TelegramClient(StringSession(session_str), api_id, api_hash)
rapor_dosyasi = "rapor.txt"
islenenler_dosyasi = "islenen_mesajlar.json"

# --- GİZLİLİK VE ŞİFRELEME FONKSİYONLARI ---
def sifrele(metin):
    """Tek yönlü SHA-256 (Mesaj ID'leri için)"""
    return hashlib.sha256(metin.encode("utf-8")).hexdigest()[:16]

def veri_kilitle(veri_dict):
    """Public depoda hedef ID ve istatistikleri gizlemek için SESSION_STRING ile şifreler."""
    raw = json.dumps(veri_dict, ensure_ascii=False).encode("utf-8")
    key = hashlib.sha256(session_str.encode("utf-8")).digest()
    xored = bytes([b ^ key[i % len(key)] for i, b in enumerate(raw)])
    return base64.b64encode(xored).decode("utf-8")

def veri_ac(sifreli_str):
    """Şifreli veriyi çözer."""
    if not sifreli_str:
        return {}
    try:
        xored = base64.b64decode(sifreli_str.encode("utf-8"))
        key = hashlib.sha256(session_str.encode("utf-8")).digest()
        raw = bytes([b ^ key[i % len(key)] for i, b in enumerate(xored)])
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {}

def islenenleri_yukle():
    if os.path.exists(islenenler_dosyasi):
        try:
            with open(islenenler_dosyasi, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"mesajlar": [], "hedef_mesaj_idleri": [], "kasa": ""}

def islenenleri_kaydet(veri):
    veri["mesajlar"] = veri["mesajlar"][-15000:]
    veri["hedef_mesaj_idleri"] = veri["hedef_mesaj_idleri"][-15000:]
    with open(islenenler_dosyasi, "w", encoding="utf-8") as f:
        json.dump(veri, f)

def rapora_yaz(metin):
    with open(rapor_dosyasi, "a", encoding="utf-8") as f:
        f.write(metin + "\n")

async def guvenli_ilet(message, baslik_bilgisi):
    try:
        await message.forward_to(HEDEF_GRUP_ID)
        await asyncio.sleep(1.2)
    except FloodWaitError as e:
        await asyncio.sleep(e.seconds + 2)
        await message.forward_to(HEDEF_GRUP_ID)
    except Exception:
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

# --- 1. MODÜL: TELEGRAM İÇİNDEN UZAKTAN KOMUT SİSTEMİ ---
async def komutlari_isle(kasa, islenen_idler):
    eklenenler = set(kasa.get("eklenen_hedefler", []))
    cikarilanlar = set(kasa.get("cikarilan_hedefler", []))
    aktif_hedefler = (set(VARSAYILAN_HEDEFLER) | eklenenler) - cikarilanlar
    istatistik_tetikle = False

    try:
        async for msg in client.iter_messages(HEDEF_GRUP_ID, limit=30):
            if not msg.text or not msg.text.startswith("/"):
                continue
            
            komut_id = sifrele(f"cmd_{msg.id}")
            if komut_id in islenen_idler:
                continue

            parcalar = msg.text.strip().split()
            komut = parcalar[0].lower()

            if komut == "/ekle" and len(parcalar) > 1 and parcalar[1].isdigit():
                yeni_id = int(parcalar[1])
                eklenenler.add(yeni_id)
                cikarilanlar.discard(yeni_id)
                aktif_hedefler.add(yeni_id)
                await msg.reply(f"✅ `{yeni_id}` hedef listesine eklendi ve takibe başlandı.")
                islenen_idler.add(komut_id)

            elif komut == "/cikar" and len(parcalar) > 1 and parcalar[1].isdigit():
                sil_id = int(parcalar[1])
                cikarilanlar.add(sil_id)
                eklenenler.discard(sil_id)
                aktif_hedefler.discard(sil_id)
                await msg.reply(f"🗑️ `{sil_id}` hedef listesinden çıkarıldı.")
                islenen_idler.add(komut_id)

            elif komut == "/liste":
                liste_metni = "\n".join([f"• `{x}`" for x in aktif_hedefler]) or "Liste boş."
                await msg.reply(f"📋 **Aktif Takip Edilen Hedefler ({len(aktif_hedefler)}):**\n{liste_metni}")
                islenen_idler.add(komut_id)

            elif komut == "/istatistik":
                istatistik_tetikle = True
                await msg.reply("📊 Haftalık istatistik ve etkileşim grafiği hazırlanıyor...")
                islenen_idler.add(komut_id)

    except Exception as e:
        print(f"Komut kontrol uyarısı: {e}")

    kasa["eklenen_hedefler"] = list(eklenenler)
    kasa["cikarilan_hedefler"] = list(cikarilanlar)
    return list(aktif_hedefler), istatistik_tetikle

# --- 2. MODÜL: PROFİL VE KİMLİK DEĞİŞİKLİĞİ RADARI (OSINT) ---
async def osint_profil_kontrol(hedefler, kasa):
    profiller = kasa.get("profiller", {})

    for hedef_id in hedefler:
        try:
            full = await client(GetFullUserRequest(hedef_id))
            user = full.users[0]
            
            yeni_veri = {
                "username": user.username or "Yok",
                "first_name": user.first_name or "",
                "last_name": user.last_name or "",
                "bio": getattr(full.full_user, 'about', '') or "Yok",
                "photo_id": str(user.photo.photo_id) if getattr(user, 'photo', None) and hasattr(user.photo, 'photo_id') else "Yok"
            }

            hid_str = str(hedef_id)
            if hid_str in profiller:
                eski = profiller[hid_str]
                degisiklikler = []

                if eski.get("username") != yeni_veri["username"]:
                    degisiklikler.append(f"🔗 **Kullanıcı Adı:** @{eski.get('username')} ➡️ @{yeni_veri['username']}")
                
                eski_ad = f"{eski.get('first_name', '')} {eski.get('last_name', '')}".strip()
                yeni_ad = f"{yeni_veri['first_name']} {yeni_veri['last_name']}".strip()
                if eski_ad != yeni_ad:
                    degisiklikler.append(f"🏷️ **İsim:** {eski_ad} ➡️ {yeni_ad}")

                if eski.get("bio") != yeni_veri["bio"]:
                    degisiklikler.append(f"📝 **Biyografi:**\nEski: `{eski.get('bio')}`\nYeni: `{yeni_veri['bio']}`")

                foto_degisti = (eski.get("photo_id") != yeni_veri["photo_id"])
                if foto_degisti:
                    degisiklikler.append("🖼️ **Profil Fotoğrafı Güncellendi!**")

                if degisiklikler:
                    bildirim = f"⚠️ **OSINT RADARI: KİMLİK DEĞİŞİKLİĞİ**\n👤 **Hedef ID:** `{hedef_id}` ({yeni_ad})\n\n" + "\n".join(degisiklikler)
                    
                    if foto_degisti and yeni_veri["photo_id"] != "Yok":
                        foto_dosya = await client.download_profile_photo(user)
                        if foto_dosya:
                            await client.send_file(HEDEF_GRUP_ID, foto_dosya, caption=bildirim)
                            os.remove(foto_dosya)
                        else:
                            await client.send_message(HEDEF_GRUP_ID, bildirim)
                    else:
                        await client.send_message(HEDEF_GRUP_ID, bildirim)

            profiller[hid_str] = yeni_veri
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"OSINT kontrol uyarısı ({hedef_id}): {e}")

    kasa["profiller"] = profiller

# --- 3. MODÜL: HAFTALIK İSTATİSTİK VE ETKİLEŞİM HARİTASI ---
async def istatistik_grafigi_gonder(kasa, manuel_mi=False):
    simdi = datetime.now(TR_TIMEZONE)
    hafta_anahtari = simdi.strftime("%Y-W%W")
    
    # Pazar günü saat 21:00 - 23:59 arası veya /istatistik komutuyla tetiklenir
    pazar_gecesi_mi = (simdi.weekday() == 6 and simdi.hour >= 21)
    if not manuel_mi:
        if not pazar_gecesi_mi or kasa.get("son_rapor_haftasi") == hafta_anahtari:
            return

    stats = kasa.get("stats", {"saatler": {}, "gruplar": {}, "etkilesimler": {}})
    if not stats.get("gruplar") and not stats.get("saatler"):
        if manuel_mi:
            await client.send_message(HEDEF_GRUP_ID, "ℹ️ Henüz grafik oluşturacak kadar istatistik verisi toplanmadı.")
        return

    try:
        plt.style.use('dark_background')
        fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(18, 6))
        fig.suptitle(f"HAFTALIK HEDEF AKTİVİTE & ETKİLEŞİM HARİTASI ({simdi.strftime('%d/%m/%Y')})", fontsize=14, fontweight='bold', color='#00ffcc')

        # 1. Grafik: Saatlik Aktiflik
        saatler = [f"{h:02d}" for h in range(24)]
        saat_degerleri = [stats.get("saatler", {}).get(str(h), 0) for h in range(24)]
        ax1.bar(saatler, saat_degerleri, color='#00bfff')
        ax1.set_title("Saatlik Aktiflik Dağılımı (TSİ)", fontsize=11)
        ax1.set_xlabel("Saat")
        ax1.set_ylabel("Mesaj Sayısı")
        ax1.tick_params(axis='x', rotation=45, labelsize=8)

        # 2. Grafik: En Çok Yazılan Gruplar (İlk 6)
        gruplar_sirali = sorted(stats.get("gruplar", {}).items(), key=lambda x: x[1], reverse=True)[:6]
        if gruplar_sirali:
            g_isimler = [x[0][:20] for x in reversed(gruplar_sirali)]
            g_sayilar = [x[1] for x in reversed(gruplar_sirali)]
            ax2.barh(g_isimler, g_sayilar, color='#ff9900')
        ax2.set_title("En Aktif Ortak Gruplar", fontsize=11)

        # 3. Grafik: En Çok Etkileşime Girilen Kişiler (İlk 6)
        etkilesim_sirali = sorted(stats.get("etkilesimler", {}).items(), key=lambda x: x[1], reverse=True)[:6]
        if etkilesim_sirali:
            e_isimler = [x[0][:22] for x in reversed(etkilesim_sirali)]
            e_sayilar = [x[1] for x in reversed(etkilesim_sirali)]
            ax3.barh(e_isimler, e_sayilar, color='#ff3366')
        ax3.set_title("En Çok Yanıtlaşılan Kişiler", fontsize=11)

        plt.tight_layout(rect=[0, 0.03, 1, 0.93])
        grafik_dosyasi = "haftalik_analiz.png"
        plt.savefig(grafik_dosyasi, dpi=150)
        plt.close()

        await client.send_file(
            HEDEF_GRUP_ID,
            grafik_dosyasi,
            caption="📈 **Haftalık Hedef Aktivite ve Etkileşim Haritası**\n\n• Saatlik aktiflik yoğunluğu\n• En sık kullanılan gruplar\n• Hedeflerle en çok yanıtlaşan kişiler"
        )
        if os.path.exists(grafik_dosyasi):
            os.remove(grafik_dosyasi)

        # Pazar gecesi otomatik gönderildiyse haftalık sayacı sıfırla
        if pazar_gecesi_mi and not manuel_mi:
            kasa["son_rapor_haftasi"] = hafta_anahtari
            kasa["stats"] = {"saatler": {}, "gruplar": {}, "etkilesimler": {}}

    except Exception as e:
        print(f"Grafik oluşturma hatası: {e}")

# --- ANA TARAMA DÖNGÜSÜ ---
async def tara_ve_raporla():
    gecmis_veri = islenenleri_yukle()
    islenen_idler = set(gecmis_veri.get("mesajlar", []))
    hedef_mesaj_idleri = set(gecmis_veri.get("hedef_mesaj_idleri", []))
    kasa = veri_ac(gecmis_veri.get("kasa", ""))

    # 1. Uzaktan Komutları İşle (/ekle, /cikar, /liste, /istatistik)
    aktif_hedefler, istatistik_tetikle = await komutlari_isle(kasa, islenen_idler)

    # 2. OSINT Profil Değişikliklerini Kontrol Et
    await osint_profil_kontrol(aktif_hedefler, kasa)

    su_an_tr = datetime.now(TR_TIMEZONE).strftime('%d/%m/%Y %H:%M')
    with open(rapor_dosyasi, "w", encoding="utf-8") as f:
        f.write(f"=== AKTİVİTE & YANIT RAPORU: {su_an_tr} (TSİ) ===\n\n")

    print(f">>> Tarama başladı... Aktif Hedef Sayısı: {len(aktif_hedefler)} (TSİ: {su_an_tr})")
    yeni_mesaj_sayisi = 0

    ortak_gruplar = {}
    for hedef_id in aktif_hedefler:
        try:
            hedef_user = await client.get_input_entity(hedef_id)
            res = await client(GetCommonChatsRequest(user_id=hedef_user, max_id=0, limit=100))
            for chat in res.chats:
                if chat.id != abs(HEDEF_GRUP_ID) and chat.id != HEDEF_GRUP_ID:
                    ortak_gruplar[chat.id] = chat
        except Exception as e:
            print(f"Ortak grup sorgu uyarısı: {e}")

    stats = kasa.get("stats", {"saatler": {}, "gruplar": {}, "etkilesimler": {}})

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
                
                hedef_mesaji_mi = (message.sender_id in aktif_hedefler)
                yanit_mi = False
                etkilesim_kisi_adi = None

                if hedef_mesaji_mi:
                    hedef_mesaj_idleri.add(gizli_id)
                    hedef_mesaj_idleri.add(ham_id)

                if message.reply_to and message.reply_to.reply_to_msg_id:
                    yanit_ham_id = f"{chat.id}_{message.reply_to.reply_to_msg_id}"
                    yanit_gizli_id = sifrele(yanit_ham_id)
                    
                    if (yanit_gizli_id in hedef_mesaj_idleri) or (yanit_ham_id in hedef_mesaj_idleri):
                        yanit_mi = True
                    else:
                        try:
                            asil_mesaj = await client.get_messages(chat, ids=message.reply_to.reply_to_msg_id)
                            if asil_mesaj:
                                if asil_mesaj.sender_id in aktif_hedefler:
                                    yanit_mi = True
                                    hedef_mesaj_idleri.add(yanit_gizli_id)
                                elif hedef_mesaji_mi:
                                    # Hedef kişi bir başkasına yanıt verdiyse etkileşime kaydet
                                    asil_gonderen = await asil_mesaj.get_sender()
                                    etkilesim_kisi_adi = getattr(asil_gonderen, 'first_name', str(asil_mesaj.sender_id))
                        except Exception:
                            pass

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
                    
                    # İstatistikleri Güncelle
                    if hedef_mesaji_mi:
                        saat_dilimi = str(mesaj_tarihi_tr.hour)
                        stats["saatler"][saat_dilimi] = stats["saatler"].get(saat_dilimi, 0) + 1
                        stats["gruplar"][chat_title] = stats["gruplar"].get(chat_title, 0) + 1
                        if etkilesim_kisi_adi:
                            stats["etkilesimler"][etkilesim_kisi_adi] = stats["etkilesimler"].get(etkilesim_kisi_adi, 0) + 1
                    elif yanit_mi:
                        stats["etkilesimler"][sender_name] = stats["etkilesimler"].get(sender_name, 0) + 1

                    etiket = "💬 [YANIT]" if yanit_mi else "👤 [HEDEF PAYLAŞIMI]"
                    detay_satiri = f"{etiket}\n[{tarih_str}] Gönderen: {sender_name} ({message.sender_id})\nTür: {tur}\nİçerik: {icerik}\nLink: {link}\n"
                    rapora_yaz(detay_satiri)
                    
                    await guvenli_ilet(message, f"{etiket} | {chat_title} | {sender_name}")
                    
                    yeni_mesaj_sayisi += 1
                    islenen_idler.add(gizli_id)

        except Exception as e:
            print(f"Grup işleme hatası: {e}")

    kasa["stats"] = stats

    # 3. Haftalık İstatistik Grafiği (Pazar gecesi veya /istatistik komutuyla)
    await istatistik_grafigi_gonder(kasa, manuel_mi=istatistik_tetikle)

    gecmis_veri["mesajlar"] = list(islenen_idler)
    gecmis_veri["hedef_mesaj_idleri"] = list(hedef_mesaj_idleri)
    gecmis_veri["kasa"] = veri_kilitle(kasa)
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
