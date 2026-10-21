import streamlit as st
import pandas as pd
import plotly.express as px
import re
from datetime import datetime

# Sayfa ayarları (Tam ekran)
st.set_page_config(layout="wide", page_title="Finansal İşlem Özeti")

# --- SOL PANEL: MANUEL GİRİŞLER ---
st.sidebar.header("Tarih ve Üye Bilgileri")
secilen_tarih = st.sidebar.text_input("Rapor Tarihi", value=datetime.today().strftime('%d.%m.%Y'))
yeni_uye = st.sidebar.number_input("Yeni Üye Sayısı", value=0, step=1)
yatirimli_yeni_uye = st.sidebar.number_input("Yatırımlı Yeni Üye", value=0, step=1)

st.sidebar.divider()

st.sidebar.header("Güncel Kripto Kurları")
st.sidebar.info("Aşağıya o günkü kurları girin. Kripto işlemler bu kurlar üzerinden hesaplanacaktır.")
kur_usdt = st.sidebar.number_input("USDT Kuru", value=46.099, step=0.001, format="%.3f")
kur_trx = st.sidebar.number_input("TRX Kuru", value=15.10, step=0.10)

# Dosya yükleme alanı
uploaded_file = st.file_uploader("Lütfen ham veri (CSV veya Excel) dosyanızı yükleyin", type=["csv", "xlsx"])

# Ana Başlık
st.title(f"Günlük Finansal İşlem Özeti | {secilen_tarih}")

if uploaded_file is not None:
    try:
        # 1. Veriyi Okuma ve Hata Koruması
        if uploaded_file.name.endswith('.csv'):
            df = pd.read_csv(uploaded_file, sep=None, engine='python')
        else:
            df = pd.read_excel(uploaded_file)
            
        # Sütunlardaki hatalı boşluk ve rakamları temizle
        df.columns = [str(col).strip() for col in df.columns]
        
        # --- SABİT SÜTUN AYARLARI ---
        islem_tipi_col = "Type"
        durum_col = "Status"
        yontem_col = "Provider"  
        tutar_col = "Amount"
        para_birimi_col = "Currency"

        beklenen_sutunlar = [islem_tipi_col, durum_col, yontem_col, tutar_col, para_birimi_col]
        eksik_sutunlar = [s for s in beklenen_sutunlar if s not in df.columns]
        
        if eksik_sutunlar:
            st.error(f"Dosyada şu sütunlar bulunamadı: {', '.join(eksik_sutunlar)}")
            st.warning(f"Dosyada bulunan sütunlar şunlar: {', '.join(map(str, df.columns))}")
        else:
            # Sadece Başarılı olanları al
            basarili_kelimeler = ['başarılı', 'success', 'onaylandı', 'approved', 'completed']
            df_basarili = df[df[durum_col].astype(str).str.lower().str.strip().isin(basarili_kelimeler)].copy()

            # --- YENİ GÜNCELLEME: GETBALANCE (ESKİ TOOPAYS) DÜZELTMESİ ---
            # Excel'de "getbalance" geçen her işlemi zorla USDT'ye çeviriyoruz
            getbalance_mask = df_basarili[yontem_col].astype(str).str.lower().str.contains('getbalance', na=False)
            df_basarili.loc[getbalance_mask, para_birimi_col] = 'USDT'
            df_basarili.loc[getbalance_mask, yontem_col] = 'GetBalance USDT'

            # --- PTPAYMENTS VE BOŞLUKLARI DÜZELTEN KISIM ---
            gecici_saglayici = df_basarili[yontem_col].astype(str).str.lower().str.strip()
            
            degisecek_satirlar = (
                gecici_saglayici.isna() | 
                (gecici_saglayici == '') | 
                (gecici_saglayici == 'nan') | 
                gecici_saglayici.str.contains('ptpayment', na=False) |
                gecici_saglayici.str.contains('pt payment', na=False)
            )
            
            def para_birimine_cevir(pb_degeri):
                pb = str(pb_degeri).upper().strip()
                if 'TRX' in pb: return 'Crypto TRX'
                if 'USDT' in pb: return 'Crypto USDT'
                return f'Crypto {pb}'

            df_basarili.loc[degisecek_satirlar, yontem_col] = df_basarili.loc[degisecek_satirlar, para_birimi_col].apply(para_birimine_cevir)

            # --- ANINDAPAY / QR AYRIMI YAPAN KISIM ---
            def aninda_ayrimi_yap(row):
                prov = str(row[yontem_col]).strip()
                if 'anındapay' in prov.lower() or 'anindapay' in prov.lower():
                    satir_metni = ' '.join(map(str, row.values)).upper()
                    if re.search(r'\bQR\b', satir_metni):
                        return 'Anında Qr'
                    else:
                        return 'Anında Havale'
                return prov

            df_basarili[yontem_col] = df_basarili.apply(aninda_ayrimi_yap, axis=1)

            # Tutar sütununu virgüllerden temizleyip sayıya çevirme
            df_basarili[tutar_col] = pd.to_numeric(df_basarili[tutar_col].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)

            # Kur Hesaplama
            def tl_hesapla(row):
                pb = str(row[para_birimi_col]).upper()
                tutar = row[tutar_col]
                if 'USDT' in pb:
                    return tutar * kur_usdt
                elif 'TRX' in pb:
                    return tutar * kur_trx
                else:
                    return tutar 

            df_basarili['TL_Karsiligi'] = df_basarili.apply(tl_hesapla, axis=1)

            # Yatırım ve Çekim ayrımı
            df_yatirim = df_basarili[df_basarili[islem_tipi_col].astype(str).str.contains('Yatırım|Deposit', case=False, na=False)]
            df_cekim = df_basarili[df_basarili[islem_tipi_col].astype(str).str.contains('Çekim|Withdraw', case=False, na=False)]

            # TÜRKÇE FORMAT FONKSİYONU
            def format_tr(val):
                return f"{val:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')

            # Yöntemlere göre sayısal verileri hazırlayan fonksiyon
            def rapor_hazirla(veri):
                if veri.empty:
                    return pd.DataFrame(columns=['Yöntem', 'İşlem Adedi', 'Toplam Tutar Num', 'Toplam_TL_Karsiligi'])
                rapor = veri.groupby(yontem_col).agg(
                    İşlem_Adedi=(yontem_col, 'count'),
                    Toplam_Tutar_Num=(tutar_col, 'sum'),
                    Toplam_TL_Karsiligi=('TL_Karsiligi', 'sum')
                ).reset_index()
                rapor.columns = ['Yöntem', 'İşlem Adedi', 'Toplam Tutar Num', 'Toplam_TL_Karsiligi']
                return rapor

            yatirim_rapor = rapor_hazirla(df_yatirim)
            cekim_rapor = rapor_hazirla(df_cekim)

            # Ekrana basılacak tablolar için Simgeli/Formatlı versiyon
            def gosterim_tablosu_hazirla(df_rapor):
                if df_rapor.empty:
                    return pd.DataFrame(columns=['Yöntem', 'İşlem Adedi', 'Toplam Tutar'])
                
                df_gosterim = df_rapor.copy()
                
                def tutar_simgesi_ekle(row):
                    yontem = str(row['Yöntem']).upper()
                    tutar = row['Toplam Tutar Num']
                    fmt_tutar = format_tr(tutar)
                    if 'USDT' in yontem:
                        return f"${fmt_tutar}"
                    elif 'TRX' in yontem:
                        return f"{fmt_tutar} TRX"
                    else:
                        return f"₺{fmt_tutar}"
                
                df_gosterim['Toplam Tutar'] = df_gosterim.apply(tutar_simgesi_ekle, axis=1)
                return df_gosterim[['Yöntem', 'İşlem Adedi', 'Toplam Tutar']]

            yatirim_gosterim = gosterim_tablosu_hazirla(yatirim_rapor)
            cekim_gosterim = gosterim_tablosu_hazirla(cekim_rapor)

            # Alt Özet Tabloları
            def ozet_tablosu_hazirla(veri):
                trx_veri = veri[veri[para_birimi_col].astype(str).str.upper().str.contains('TRX')]
                usdt_veri = veri[veri[para_birimi_col].astype(str).str.upper().str.contains('USDT')]
                tl_veri = veri[~veri[para_birimi_col].astype(str).str.upper().str.contains('TRX|USDT')]
                
                ozet_df = pd.DataFrame({
                    "ÖZET": ["TOPLAM TRX", "TOPLAM USDT", "TOPLAM TL", "GENEL TOPLAM (Kur Dahil)"],
                    "ADET": [
                        len(trx_veri), 
                        len(usdt_veri), 
                        len(tl_veri), 
                        len(veri)
                    ],
                    "TUTAR": [
                        f"{format_tr(trx_veri[tutar_col].sum())} TRX",
                        f"${format_tr(usdt_veri[tutar_col].sum())}",
                        f"₺{format_tr(tl_veri[tutar_col].sum())}",
                        f"₺{format_tr(veri['TL_Karsiligi'].sum())}"
                    ]
                })
                return ozet_df

            yatirim_ozet = ozet_tablosu_hazirla(df_yatirim)
            cekim_ozet = ozet_tablosu_hazirla(df_cekim)

            # --- 1. SATIR: ANA TABLOLAR ---
            st.divider()
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("<h3 style='text-align: center; color: #2e7b32; background-color: #e8f5e9; padding: 10px; border-radius: 5px;'>YATIRIM</h3>", unsafe_allow_html=True)
                st.table(yatirim_gosterim.set_index('Yöntem'))
                
            with col2:
                st.markdown("<h3 style='text-align: center; color: #c62828; background-color: #ffebee; padding: 10px; border-radius: 5px;'>ÇEKİM</h3>", unsafe_allow_html=True)
                st.table(cekim_gosterim.set_index('Yöntem'))

            # --- 2. SATIR: ÖZET TABLOLAR ---
            st.divider()
            col3, col4 = st.columns(2)
            
            with col3:
                st.markdown("<b>YATIRIM ÖZETİ</b>", unsafe_allow_html=True)
                st.table(yatirim_ozet.set_index('ÖZET'))
                
            with col4:
                st.markdown("<b>ÇEKİM ÖZETİ</b>", unsafe_allow_html=True)
                st.table(cekim_ozet.set_index('ÖZET'))
                
            # --- 3. SATIR: ÜYE BİLGİLERİ ---
            st.divider()
            mcol1, mcol2 = st.columns(2)
            with mcol1:
                st.metric(label="Yeni Üye", value=yeni_uye)
            with mcol2:
                st.metric(label="Yatırımlı Yeni Üye", value=yatirimli_yeni_uye)

            # --- 4. SATIR: PASTA GRAFİKLERİ ---
            st.divider()
            g1, g2 = st.columns(2)
            with g1:
                if not yatirim_rapor.empty:
                    fig_yatirim = px.pie(yatirim_rapor, values='Toplam_TL_Karsiligi', names='Yöntem', hole=0.4)
                    fig_yatirim.update_layout(title_text='Yatırım Yöntemleri Dağılımı (Hacim Ağırlıklı)', title_x=0.5)
                    st.plotly_chart(fig_yatirim, use_container_width=True)
            with g2:
                if not cekim_rapor.empty:
                    fig_cekim = px.pie(cekim_rapor, values='Toplam_TL_Karsiligi', names='Yöntem', hole=0.4)
                    fig_cekim.update_layout(title_text='Çekim Yöntemleri Dağılımı (Hacim Ağırlıklı)', title_x=0.5)
                    st.plotly_chart(fig_cekim, use_container_width=True)

    except Exception as e:
        st.error(f"Veri işlenirken bir hata oluştu. Hata detayı: {e}")
