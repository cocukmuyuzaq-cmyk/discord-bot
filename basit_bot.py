import discord
from discord.ext import commands
from openai import OpenAI
import json
import time
from collections import deque

with open('config.json', 'r') as f:
    config = json.load(f)

DISCORD_TOKEN = config['DISCORD_TOKEN']
CEREBRAS_API_KEY = config['CEREBRAS_API_KEY']

client = OpenAI(
    api_key=CEREBRAS_API_KEY,
    base_url="https://api.cerebras.ai/v1"
)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Her kullanıcı için ayrı sohbet geçmişi (SON 50 MESAJ - Uzun hafıza!)
# Deque ile otomatik sınırlama
sohbet_gecmisi = {}
kullanici_limit = {}

# Ayarlar
MAX_HISTORY = 50  # Önceki 50 mesajı hatırla! (Cerebras 8K token'a kadar çıkar)
MAX_TOKENS = 800  # Cevap uzunluğu (yüksek)
RATE_LIMIT = 5    # Dakikada 5 istek

@bot.event
async def on_ready():
    print(f'✅ {bot.user} olarak giriş yapıldı!')
    print(f'🧠 Her kullanıcı SON {MAX_HISTORY} mesajı hatırlayacak!')
    print(f'📝 Maksimum cevap uzunluğu: {MAX_TOKENS} token')
    print(f'⚡ Cerebras AI hazır (Saniyede 2000 token)')
    await bot.change_presence(activity=discord.Game(name="!ai | Uzun hafızalı 🤖"))

def rate_limit_check(kullanici_id):
    """Dakikada 5 istek kontrolü"""
    now = time.time()
    if kullanici_id not in kullanici_limit:
        kullanici_limit[kullanici_id] = []
    
    kullanici_limit[kullanici_id] = [t for t in kullanici_limit[kullanici_id] if now - t < 60]
    
    if len(kullanici_limit[kullanici_id]) >= RATE_LIMIT:
        return False
    return True

def add_rate_limit(kullanici_id):
    if kullanici_id not in kullanici_limit:
        kullanici_limit[kullanici_id] = []
    kullanici_limit[kullanici_id].append(time.time())

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    if bot.user in message.mentions or message.content.startswith('!ai'):
        await ai_cevapla(message)
        return
    
    await bot.process_commands(message)

async def ai_cevapla(message):
    kullanici_id = str(message.author.id)
    soru = message.content.replace(f'<@{bot.user.id}>', '').replace('!ai', '').strip()
    
    if not soru:
        await message.reply("Bir şey sor kanka! Örnek: `!ai dün ne konuştuk?`")
        return
    
    # Rate limit
    if not rate_limit_check(kullanici_id):
        await message.reply(f"⏰ Dakikada {RATE_LIMIT} istek hakkın var! Biraz bekle.")
        return
    
    # Sohbet geçmişini hazırla (uzun hafıza - son 50 mesaj)
    if kullanici_id not in sohbet_gecmisi:
        sohbet_gecmisi[kullanici_id] = deque(maxlen=MAX_HISTORY)
        sohbet_gecmisi[kullanici_id].append({
            "role": "system", 
            "content": f"Sen uzun sohbet hafızalı bir asistansın. Önceki mesajları hatırlıyorsun. Türkçe konuş, detaylı ve net cevap ver. Maksimum cevap uzunluğun {MAX_TOKENS} token."
        })
    
    # Kullanıcı mesajını ekle
    sohbet_gecmisi[kullanici_id].append({"role": "user", "content": soru})
    
    # API'ye gönderilecek mesajları hazırla (deque'yi listeye çevir)
    messages_list = list(sohbet_gecmisi[kullanici_id])
    
    dusunuyor = await message.reply("🤔 Düşünüyorum (önceki mesajları hatırlıyorum)...")
    
    try:
        # Cerebras API isteği - yüksek token limitli
        response = client.chat.completions.create(
            model="llama3.1-8b",  # veya "llama3.1-70b" daha kaliteli
            messages=messages_list,
            max_tokens=MAX_TOKENS,  # 800 token uzun cevap!
            temperature=0.7
        )
        
        cevap = response.choices[0].message.content
        
        # Asistan cevabını geçmişe ekle
        sohbet_gecmisi[kullanici_id].append({"role": "assistant", "content": cevap})
        add_rate_limit(kullanici_id)
        
        await dusunuyor.delete()
        
        # Uzun cevapları parçala
        if len(cevap) > 1900:
            parcalar = [cevap[i:i+1900] for i in range(0, len(cevap), 1900)]
            for parca in parcalar:
                await message.reply(parca)
        else:
            await message.reply(cevap)
            
    except Exception as e:
        await dusunuyor.delete()
        hata = str(e)
        print(f"Hata: {hata}")
        
        if "401" in hata:
            await message.reply("❌ API Key geçersiz! `csk-` ile başlıyor mu kontrol et.")
        elif "429" in hata:
            await message.reply("⏰ Rate limit! 1 dakika bekle.")
        else:
            await message.reply(f"❌ Hata: `{hata[:200]}`")

# ================= KOMUTLAR =================

@bot.command()
async def ai(ctx, *, soru=None):
    """AI ile sohbet et (önceki mesajları hatırlar)"""
    if not soru:
        await ctx.send("❗ Kullanım: `!ai <sorun>`\nÖrnek: `!ai dün ne konuştuk?`")
        return
    
    kullanici_id = str(ctx.author.id)
    
    if kullanici_id not in sohbet_gecmisi:
        sohbet_gecmisi[kullanici_id] = deque(maxlen=MAX_HISTORY)
        sohbet_gecmisi[kullanici_id].append({
            "role": "system", 
            "content": f"Sen uzun sohbet hafızalı bir asistansın. Türkçe konuş, detaylı ve net cevap ver."
        })
    
    sohbet_gecmisi[kullanici_id].append({"role": "user", "content": soru})
    messages_list = list(sohbet_gecmisi[kullanici_id])
    
    async with ctx.typing():
        try:
            response = client.chat.completions.create(
                model="llama3.1-8b",
                messages=messages_list,
                max_tokens=MAX_TOKENS,
                temperature=0.7
            )
            
            cevap = response.choices[0].message.content
            sohbet_gecmisi[kullanici_id].append({"role": "assistant", "content": cevap})
            
            if len(cevap) > 1900:
                await ctx.send(cevap[:1900] + "...")
            else:
                await ctx.send(cevap)
                
        except Exception as e:
            await ctx.send(f"❌ Hata: {str(e)[:150]}")

@bot.command()
async def hafiza(ctx):
    """Kaç mesaj hatırladığını göster"""
    kullanici_id = str(ctx.author.id)
    if kullanici_id in sohbet_gecmisi:
        mesaj_sayisi = len(sohbet_gecmisi[kullanici_id]) - 1  # System mesajı çıkar
        await ctx.send(f"🧠 **{mesaj_sayisi}** mesaj hatırlıyorum! (Maksimum {MAX_HISTORY})")
    else:
        await ctx.send("🧠 Henüz hiç sohbetimiz yok! Bana bir şey sor :)")

@bot.command()
async def temizle(ctx):
    """Sohbet geçmişini temizle"""
    kullanici_id = str(ctx.author.id)
    if kullanici_id in sohbet_gecmisi:
        sohbet_gecmisi[kullanici_id] = deque(maxlen=MAX_HISTORY)
        sohbet_gecmisi[kullanici_id].append({
            "role": "system", 
            "content": f"Sen uzun sohbet hafızalı bir asistansın. Türkçe konuş, detaylı ve net cevap ver."
        })
    await ctx.send("🧹 Sohbet geçmişin temizlendi! Artık beni yeni tanıyorsun.")

@bot.command()
async def ayarlar(ctx, max_mesaj: int = None):
    """Hafıza boyutunu ayarla (örn: !ayarlar 100)"""
    global MAX_HISTORY
    if max_mesaj and await bot.is_owner(ctx.author):
        if 10 <= max_mesaj <= 200:
            MAX_HISTORY = max_mesaj
            # Mevcut kullanıcıların geçmişlerini yeniden boyutlandır
            for uid in sohbet_gecmisi:
                sohbet_gecmisi[uid] = deque(list(sohbet_gecmisi[uid]), maxlen=MAX_HISTORY)
            await ctx.send(f"✅ Hafıza boyutu **{MAX_HISTORY}** mesaj olarak ayarlandı!")
        else:
            await ctx.send("❌ 10-200 arası bir değer girin!")
    else:
        await ctx.send(f"📊 Şu an **{MAX_HISTORY}** mesaj hatırlıyorum. (Sadece bot sahibi değiştirebilir)")

@bot.command()
async def ping(ctx):
    """Bot gecikmesini göster"""
    await ctx.send(f"🏓 Pong! {round(bot.latency * 1000)}ms")

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)