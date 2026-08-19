# Kotone

Kotoneは、任意のバイナリデータをPCM音声へ変換し、音声から元のデータを復元するData over Audioシステムです。このリポジトリは、チャンネルに依存しないPythonリファレンス実装です。

現在のv0.1は、開発マイルストーン1（Digital Loopback）と2（WAV）の基礎を実装しています。

- 44.1/48 kHz / signed 16-bit / mono・stereo WAV
- mono/stereo 4-FSKと、raw 96,000 bit/sのstereo 8-PSK OFDM
- Reed–Solomon FECとinterleaveによるSBC byte error訂正
- レジストリから差し替え可能なModem実装
- 複数パケットへの分割、Stream ID、Sequence Number
- パケット単位のCRC32検証と欠落検出
- 対応受信側が発行した5桁IDから未受信パケットだけを再送
- Windowsの既定スピーカーへ直接ストリーミング再生する`kotone send`
- UTF-8ファイル名、本文サイズ、本文CRC32を持つKTF1 file payload
- `bytes -> PCM -> bytes` API
- メモリ使用量を抑えたストリーミングWAV書き込み・読み込み
- Goodput、raw bitrate、BER、PER、CRC error、lost packet、処理時間の計測
- SHA-256を含む自動round-trip test

FFmpeg SBC simulation、Reed–Solomon FEC、Windows WaveOut送信を実装済みです。Atom LiteのA2DP受信では`a2dp-ofdm-441`を既定値とします。WaveOutへPCMを渡した後のSBC変換とBluetooth A2DP送信はWindowsが担当します。Kotone自身によるBluetoothスタックの直接制御、Opus、WASAPI Loopback、マイク入力を使う汎用的な実音響受信はまだ実装していません。

## セットアップ

Python 3.12以降と[uv](https://docs.astral.sh/uv/)を使用します。

```powershell
git clone https://github.com/hachiware-labs/kotone.git
cd .\kotone
uv sync
uv run kotone --help
```

SBCシミュレーションを使う場合は、FFmpegをPATHへ追加するか、バンドル版を含むoptional dependencyを導入します。

```powershell
uv sync --extra sbc
```

## CLI

### ファイルを送信する

KotoneをインストールしたWindowsでは、次の1行が通常の送信手順です。

```powershell
kotone send .\資料.bin
```

既定では`a2dp-ofdm-441`でKTF1/packet/OFDM PCMを生成し、Windowsで現在選択
されている既定のスピーカーへ再生します。`Kotone Atom Speaker`を既定の出力先に
しておけば、そのままWindowsのPCM→SBC→Bluetooth A2DP経路でAtom Liteへ届きます。
WAVの事前生成、別プロジェクトの再生スクリプト、USB serial接続は必要ありません。

先頭へ500 ms、末尾へ1秒の無音を付け、すべてのWaveOut bufferの再生完了まで待機
します。Ctrl+Cやエラー時はWaveOutをresetして安全に停止します。入力は複数回走査して
CRCを計算しますが、ファイル全体、生成PCM全体、WAV全体をRAMへ保持せず、packet単位
で符号化して少数のWaveOut bufferへqueueします。

出力先やprofileを明示する必要がある場合だけ指定します。`--device`はWaveOutデバイス
名の一部または数値IDです。

```powershell
kotone send .\資料.bin --device "Kotone Atom Speaker"
kotone send .\資料.bin --profile a2dp-ofdm-328-robust
```

`send`はWindows WaveOut専用です。Windows以外では非対応エラーを表示し、音声出力は
行いません。

### WAVを生成・解析する

検証やファイル経由の利用では、encode、noise付与、decodeを独立して実行できます。

```powershell
uv run kotone encode input.bin clean.wav --profile a2dp-ofdm-328-robust
uv run kotone noise clean.wav noisy.wav --snr-db 20 --seed 42
uv run kotone decode noisy.wav restored.bin --profile a2dp-ofdm-328-robust
```

`a2dp-ofdm-441`でファイルを44.1 kHzのWAVへ変換し、元のファイル名で復元する
PowerShellの実行例です。

```powershell
uv run kotone encode .\資料.bin .\send.wav --profile a2dp-ofdm-441
uv run kotone decode .\send.wav --profile a2dp-ofdm-441
```

`encode`は入力ファイルのbasename（この例では`資料.bin`）をUTF-8でpayload先頭へ
埋め込みます。`decode`の出力ファイルを省略すると、その名前を検証し、現在の
ディレクトリへ`資料.bin`として復元します。既に同名ファイルがある場合は上書き
されるため、必要なら先に別の場所へ移動してください。

`atom-lite-kotone`のPC受信スクリプトがpacket欠落やtimeoutを検出して
`RESUME_ID=00A3F`のような5桁IDを表示した場合は、同じ入力ファイルから未受信packet
だけを含むPCMを直接再送できます。

```powershell
kotone send .\資料.bin --resume 00A3F
```

PC受信側は5桁16進連番を発行し、元streamのID、次に必要なsequence、受信済みbyte数、
途中CRC、packet sizeを`%LOCALAPPDATA%\Kotone\resume\<ID>.json`へ保存します。Kotoneは
IDからこの状態を読みます。入力ファイルの内容・ファイル名・packet sizeが元の送信と
一致しない場合は送信を拒否します。再送PCMはSTARTから送り直さず、指定sequenceから
元の番号とstream IDを保ってENDまでを送ります。WAVとして保存したい検証用途では
`kotone encode 入力 出力.wav --resume 00A3F`も利用できます。

v0.1では5桁IDの受け渡しと`send`の再実行は手動です。このリポジトリのPython
decoderはIDを発行せず、元WAVと再開WAVを結合して復元する機能もありません。
再開にはPC受信側に途中データが保持されている必要があります。受信側を停止
した場合の`.part`復元方法を含む受信手順は`atom-lite-kotone`のREADMEを参照して
ください。

Kotoneの`send --resume`と`atom-lite-kotone`のPC受信側との5桁ID相互運用には
対応済みです。一方、`stack-chan-kotone`の現行SD受信コードは異常時に`.part`を削除
し、resume IDの発行・途中データの復元を行わないため、Stack-chan SD受信側でのresumeは
まだ利用できません。その場合は先頭から送信し直してください。

`noise`はWAV全体のRMSを測定して指定SNRのwhite Gaussian noiseを付与します。`--seed`を指定すると同一条件を再現できます。mono/stereo、sample rate、frame数を維持し、large WAVもchunk単位で処理します。

同じ入力データから、全Modemプロファイルの短い試聴用WAVをまとめて生成できます。

```powershell
uv run kotone demo input.bin demo-audio --duration 3
```

特定方式だけを比較する場合：

```powershell
uv run kotone demo input.bin demo-audio --profiles reliable a2dp-ofdm-328-robust a2dp-ofdm
```

バイナリをWAVに変換します。

```powershell
uv run kotone encode input.bin output.wav
uv run kotone encode input.bin output-fast.wav --profile fast
uv run kotone encode input.bin output-a2dp.wav --profile a2dp
uv run kotone encode input.bin output-stereo.wav --profile a2dp-stereo
uv run kotone encode input.bin output-stereo-fec.wav --profile a2dp-stereo-fec
uv run kotone encode input.bin output-ofdm-441.wav --profile a2dp-ofdm-441
uv run kotone encode input.bin output-ofdm-328.wav --profile a2dp-ofdm-328
uv run kotone encode input.bin output-robust.wav --profile a2dp-ofdm-328-robust
uv run kotone encode input.bin output-ofdm.wav --profile a2dp-ofdm
```

`a2dp-ofdm-441`のWAV出力には、A2DP/SBC経路が安定する前に取得波形が欠けないよう、既定で先頭へ500 msの無音を追加します。値は`--startup-silence-ms`で変更でき、`--startup-silence-ms 0`で無効化できます。Python APIでは`encode_wav(..., startup_silence_seconds=0.5)`のように明示します。

Atom Lite実機では、この500 msガード付きWAVから取得相関score 1.000で同期し、4個のPHYヘッダー（sequence 0〜3）をすべて検出しました。ガードなしではA2DP開始直後の取得波形が崩れ、全体相関scoreが0.354まで低下して同期できませんでした。

Atom Liteの組み込みデコーダーによる実機payload試験では、4パケット・14,118 bytesを復元しました。実A2DP/SBC経路で発生した2 byte errorをRSで訂正し、PHY CRC error、packet CRC error、lost packetはいずれも0、最終stream CRCは送信時stream IDと一致しました。

WAVから元のバイナリを復元します。完全なストリームがない場合やCRCエラー・パケット欠落がある場合は、出力を書かずに非ゼロで終了します。

```powershell
uv run kotone decode output.wav restored.bin
uv run kotone decode output-fast.wav restored.bin --profile fast
uv run kotone decode output-a2dp.wav restored.bin --profile a2dp
uv run kotone decode output-stereo.wav restored.bin --profile a2dp-stereo
uv run kotone decode output-stereo-fec.wav restored.bin --profile a2dp-stereo-fec
uv run kotone decode output-ofdm-441.wav restored.bin --profile a2dp-ofdm-441
uv run kotone decode output-ofdm-328.wav restored.bin --profile a2dp-ofdm-328
uv run kotone decode output-robust.wav restored.bin --profile a2dp-ofdm-328-robust
uv run kotone decode output-ofdm.wav restored.bin --profile a2dp-ofdm
```

KTF1形式なら出力引数を省略できます。旧形式にはファイル名がないため、従来どおり
出力引数が必要です。受信名にパス、制御文字、Windows予約名などが含まれる場合は
復元を拒否します。

デジタルループバックの性能を測定します。

```powershell
uv run kotone bench input.bin
uv run kotone bench input.bin --profile fast
uv run kotone bench input.bin --profile a2dp --channel sbc
uv run kotone bench input.bin --profile a2dp-stereo --channel sbc
uv run kotone bench input.bin --profile a2dp-stereo-fec --channel sbc
uv run kotone bench input.bin --profile a2dp-ofdm-441 --channel sbc
uv run kotone bench input.bin --profile a2dp-ofdm-328 --channel sbc
uv run kotone bench input.bin --profile a2dp-ofdm-328-robust --channel sbc
uv run kotone bench input.bin --profile a2dp-ofdm --channel sbc
uv run kotone bench input.bin --json
```

パケットpayloadは既定で512 bytes、`a2dp-ofdm-441`と`a2dp-ofdm-328`系では4096 bytes、`a2dp-ofdm`では1024 bytesです。`--packet-size`で1〜65535 bytesに変更できます。符号化と復号には同じ`--profile`を指定してください。

## Python API

```python
from kotone import codec_config_for_profile, decode, encode

original = b"arbitrary binary \x00\xff"
pcm = encode(original)  # mono float32 ndarray, nominal range -1.0..1.0
restored = decode(pcm)

assert restored == original

fast = codec_config_for_profile("fast")
fast_pcm = encode(original, fast)  # 4,800 symbols/s = 9,600 raw bit/s
assert decode(fast_pcm, fast) == original

a2dp = codec_config_for_profile("a2dp")
a2dp_pcm = encode(original, a2dp)  # 6,000 symbols/s = 12,000 raw bit/s
assert decode(a2dp_pcm, a2dp) == original

stereo = codec_config_for_profile("a2dp-stereo")
stereo_pcm = encode(original, stereo)  # shape: (frames, 2), raw 19,200 bit/s
assert decode(stereo_pcm, stereo) == original

stereo_fec = codec_config_for_profile("a2dp-stereo-fec")
protected_pcm = encode(original, stereo_fec)  # raw 24,000 bit/s + RS FEC
assert decode(protected_pcm, stereo_fec) == original

ofdm_441 = codec_config_for_profile("a2dp-ofdm-441")
cd_rate_pcm = encode(original, ofdm_441)  # 44.1 kHz stereo, raw 67,200 bit/s
assert decode(cd_rate_pcm, ofdm_441) == original

ofdm_328 = codec_config_for_profile("a2dp-ofdm-328")
qpsk_pcm = encode(original, ofdm_328)  # stereo QPSK OFDM, raw 64,000 bit/s
assert decode(qpsk_pcm, ofdm_328) == original

robust = codec_config_for_profile("a2dp-ofdm-328-robust")
robust_pcm = encode(original, robust)  # 32 parity symbols / codeword
assert decode(robust_pcm, robust) == original

ofdm = codec_config_for_profile("a2dp-ofdm")
ofdm_pcm = encode(original, ofdm)  # stereo 8-PSK OFDM, raw 96,000 bit/s
assert decode(ofdm_pcm, ofdm) == original
```

WAV adapterはパケット単位でPCMを処理するため、ファイル全体に相当するfloat配列を保持しません。

```python
from kotone.channel import decode_wav, encode_wav

encode_wav(original, "output.wav")
restored = decode_wav("output.wav")
```

受信PCMを分割して渡す場合は`Decoder`を使えます。v0.1のストリーミングdecoderはsymbol境界に揃ったKotone信号を前提とします。

```python
from kotone import Decoder

decoder = Decoder()
for pcm_chunk in pcm_source:
    decoder.push(pcm_chunk)
report = decoder.finish()
```

## フレーム形式

CLIでファイルを符号化すると、元データを次のKTF1 file payloadへ包んでから
Kotone packetへ分割します。整数はnetwork byte orderです。Stream IDは
「KTF1ヘッダー＋UTF-8ファイル名＋ファイル本文」全体のCRC32です。

| Field | Size | 内容 |
| --- | ---: | --- |
| Magic | 4 bytes | ASCII `KTF1` |
| Version | 1 byte | 現在は`1` |
| Flags | 1 byte | 現在は`0` |
| Header length | 2 bytes | 固定24 bytes＋ファイル名長 |
| Filename length | 2 bytes | UTF-8で1〜255 bytes |
| Reserved | 2 bytes | `0` |
| File size | 8 bytes | ファイル本文のbyte数 |
| File CRC32 | 4 bytes | ファイル本文だけのCRC32 |
| Filename | 可変長 | パスを含まないUTF-8 basename |
| File data | 可変長 | 元のファイル本文 |

Python APIの`encode(bytes)`は従来どおり任意bytesをそのまま送ります。ファイル形式を
APIから使う場合は`pack_file_payload()`と`unpack_file_payload()`を明示的に使います。

各パケットは次の順で送信されます。整数はnetwork byte orderです。

| Field | Size | 内容 |
| --- | ---: | --- |
| Preamble | 8 bytes | `0x55`の反復 |
| Sync word | 4 bytes | `D3 91 C5 A7` |
| Protocol version | 1 byte | 現在は`1` |
| Flags | 1 byte | START / END |
| Stream ID | 4 bytes | データ全体のCRC32を既定値として利用 |
| Sequence number | 4 bytes | 0から始まるパケット番号 |
| Payload length | 2 bytes | 0〜65535 |
| Payload | 可変長 | 任意のbytes |
| CRC32 | 4 bytes | headerとpayloadを検証 |

4-FSKでは1 byteを4 symbols（2 bits/symbol）へ変換します。`reliable`プロファイルのtoneは2400、3600、4800、6000 Hzで、40 samples/symbolです。`fast`は4800、9600、14400、19200 Hz、10 samples/symbol、`a2dp`は3000、9000、15000、21000 Hz、8 samples/symbolを使います。各toneはsymbol境界でゼロへ戻り、Python実装と将来の組み込み実装の対応を単純に保てます。

`a2dp-stereo`は左右チャンネルを独立した4-FSK laneとして使います。各laneは4800 symbols/s、toneは2400、7200、12000、16800 Hzです。framed bytesを偶数・奇数位置で2 laneへ分配し、lane sequence、length、CRC32を持つ物理フレームで再結合します。片方の物理フレームが壊れても、sequenceによって後続packetのlane対応がずれません。

`a2dp-stereo-fec`は各laneを6000 symbols/sへ上げ、toneを3000、8000、13000、18000 Hzとします。laneデータはGF(2^8)のReed–Solomon codeで247 data bytesごとに8 parity bytesを付加し、最大4 byte errorを訂正します。複数codewordをcolumn方向へinterleaveするため、SBCの連続byte errorが一つのcodewordへ集中しにくい構造です。FEC後も元データのCRC32を検証します。

OFDMプロファイルは左右それぞれ16 carriersを使います。CD/A2DP向けの`a2dp-ofdm-441`は44.1 kHz、42 samples/symbol、2.1〜17.85 kHzのQPSKでstereo合計raw 67200 bit/sです。`a2dp-ofdm-328`は48 kHz、2〜17 kHzのQPSKでraw 64000 bit/s、`a2dp-ofdm`は8-PSKでraw 96000 bit/sです。いずれもstream先頭専用の4-block acquisition、packetごとの2-block sync、3重化header、channel推定、RS FEC、interleave、CRC32を使用します。

## 容量と速度

既定設定のraw bitrateは2400 bit/s（300 raw bytes/s）です。512-byte payloadではフレームoverheadを含む理論payload goodputは約284 B/sです。`fast`プロファイルはraw 9600 bit/s（1200 raw bytes/s）で、同じpayloadサイズの理論payload goodputは約1.13 kB/sです。

`a2dp`プロファイルはraw 12000 bit/s、実効payload約1.42 kB/s（約11.3 kbit/s）です。48 kHz stereo、328 kbit/sのFFmpeg SBC encode/decodeを通す自動テストで完全復元を確認します。SBC encoder設定や実機のDSPは製品ごとに異なるため、この結果は全A2DP機器での保証ではありません。

`a2dp-stereo`はraw 19200 bit/s、実効payload約2.1 kB/s（約16.8 kbit/s）です。同じ328 kbit/s SBC試験でBER、PER、CRC errorがすべて0になることを確認しています。

`a2dp-stereo-fec`はraw 24000 bit/s、実効payload約2.49 kB/s（約19.95 kbit/s）です。256 KiB・512 packetsの328 kbit/s SBC試験では13 byte errorをFECで訂正し、BER、PER、CRC error、lost packetsがすべて0でした。256 KiBを5回、合計1.25 MiB・2560 packets連続で完全復元する追加試験も通過しています。

`a2dp-ofdm-441`はCD音源とWindows A2DPで一般的な44.1 kHzをそのまま使い、途中の44.1↔48 kHz変換を避けるAtom Lite向けプロファイルです。raw 67200 bit/s、README 13002 bytesによる実測goodputは約7.60 kB/sでした。44.1 kHz stereo / 328 kbit/sのFFmpeg SBC試験でBER、PER、CRC error、lost packetsがすべて0となり、完全復元しています。

`a2dp-ofdm-328`はraw 64000 bit/s、実効payload約7.30 kB/s（約58.4 kbit/s）です。256 KiBを5回、合計1.25 MiB・320 packetsの328 kbit/s SBC試験ですべて完全復元し、うち1 byte-symbolをFECで訂正しました。従来の`a2dp-stereo-fec`の約2.93倍です。

`a2dp-ofdm-328-robust`はReed–Solomon parityを16から32 symbolsへ増やし、1 codewordあたり最大16 byte-symbol errorを訂正します。実効payloadは約6.77 kB/s（約54.2 kbit/s）、1時間あたり約24.4 MBです。速度低下を約7%に抑えながら訂正能力を2倍にしています。

`a2dp-ofdm`はraw 96000 bit/s、実効payload約10.45 kB/s（約83.6 kbit/s）です。256 KiB・256 packetsを48 kHz stereo / 512 kbit/s SBCへ通し、BER、PER、CRC error、lost packetsがすべて0で完全復元しました。100 MBの理論転送時間は約160分です。

512 kbit/s SBCはすべてのA2DP機器が受け入れるとは限りません。対応しない機器では328 kbit/s向けの`a2dp-stereo-fec`を使用します。

`fast`は無変換WAV向け、`a2dp`はmono SBC/A2DP評価向けです。mono 4-FSKではraw 16000 bit/sで全packetにCRC errorが生じました。そこで単一laneを無理に高速化せず、SBCを通る速度のlaneをstereoで並列化しています。

## Modemの追加

Codecは`ModemConfig.scheme`をキーにModem factoryを選びます。組み込み方式は`4fsk`、`stereo-4fsk`、`stereo-ofdm-psk`です。

```python
from kotone import available_modems, register_modem

print(available_modems())  # ('4fsk', 'stereo-4fsk', 'stereo-ofdm-psk')
register_modem("my-modem", MyModem)
```

追加するModemは`modulate(data)`, `demodulate(samples)`, `new_demodulator()`と`config`を提供します。Framing、CRC、WAV、benchmark、CLIの処理はModem実装から分離されています。

既定の`reliable`では1 MiBが約62分の音声になります。`a2dp-ofdm`の実測goodputでは約100秒です。日常の自動テストは短時間で終わるデータを使い、長時間SBC試験は別途実行します。

## テスト

```powershell
uv run pytest
```

テストは空データ、ランダムバイナリ、複数パケット、CRC破損、サンプル境界のずれ、WAV、CLI、benchmarkを検証します。

## 構成

```text
src/kotone/
├── framing/    # packet、sync、CRC32、順序・欠落検出
├── fec/        # Identity / Reed–Solomon + interleave
├── modem/      # 交換可能なmodem境界と4-FSK
├── channel/    # WAV adapter
├── benchmark/  # loopback計測
├── codec.py    # Binary ↔ PCM API
└── cli.py
```
