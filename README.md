# blender-comparison-logger

3DCG学習支援アドオンの比較実験（既存アドオン版 vs 既存学習方法：動画版）のうち、
**動画版（既存学習方法）を担当する参加者用**の、バックグラウンド操作ログ記録アドオンです。

チュートリアルUIやヒント表示は一切行いません。参加者の操作を裏で検知し、
JSONLログとして記録するだけの「サイレント計測」アドオンです
（自動判定フィードバックがあると比較実験の前提が崩れるため）。

## 導入方法

1. 「Code」→「Download ZIP」でこのリポジトリをダウンロード（解凍不要）
2. Blenderの環境設定 → アドオン → 右上「∨」→「ディスクからインストール」でこのZIPを選択
3. 3Dビューのサイドバー（Nキー）→「Logger」タブを開く
4. 参加者IDとログ保存フォルダを設定し、「計測開始」を押してから動画を見ながら作業を進める

## 集計

`23DB000/jsonl_to_category_summary_csv.py` で、記録したJSONLログをCSVに集計できます。

```
python jsonl_to_category_summary_csv.py <participant_log.jsonl>
python jsonl_to_category_summary_csv.py <jsonlが入っているフォルダ>
```
