#!/bin/bash
#SBATCH -p bosch_gpu-rtx2080
#SBATCH --gres=gpu:1
#SBATCH -t 1-00:00:00 # time (D-HH:MM)
#SBATCH -c 2 # number of cores
#SBATCH -o logs/%j.%x.%N.out # STDOUT  (the folder log has to be created prior to running or this won't work)
#SBATCH -e logs/%j.%x.%N.err # STDERR  (the folder log has to be created prior to running or this won't work)
#SBATCH -J charlm # sets the job name. If not specified, the file name will be used as job name
#SBATCH --mail-type=END,FAIL # (recive mails about end and timeouts/crashes of your job)
#python search_spaces/CharLM/search/search.py --mixop darts_v1 --portion 0.5 --use_we_v2
#python search_spaces/CharLM/search/search.py --mixop drnas --portion 0.5 --use_we_v2
#python toy_search_spaces/conv_macro/train_search.py --optimizer_type drnas --train_portion 0.8
# {'num_layers': 5, 'embed_dim': 384, 'num_heads': [6, 6, 6, 6, 6, 6], 'mlp_ratio': [3, 3, 3, 3, 2, 2]}
python toy_search_spaces/nanoGPT/train_base.py --config toy_search_spaces/nanoGPT/config/train_shakespeare_char_base.py --depth 5 --embed_dim 384  --num_heads 6 --num_heads 6 --num_heads 6 --num_heads 6 --num_heads 6 --num_heads 6  --mlp_ratio 3 --mlp_ratio 3 --mlp_ratio 3 --mlp_ratio 3 --mlp_ratio 2  --mlp_ratio 2 --seed 9001 --optimizer drnas_0.8
python toy_search_spaces/nanoGPT/train_base.py --config toy_search_spaces/nanoGPT/config/train_shakespeare_char_base.py --depth 5 --embed_dim 384  --num_heads 6 --num_heads 6 --num_heads 6 --num_heads 6 --num_heads 6 --num_heads 6  --mlp_ratio 3 --mlp_ratio 3 --mlp_ratio 3 --mlp_ratio 3 --mlp_ratio 2  --mlp_ratio 2 --seed 9002 --optimizer drnas_0.8
python toy_search_spaces/nanoGPT/train_base.py --config toy_search_spaces/nanoGPT/config/train_shakespeare_char_base.py --depth 5 --embed_dim 384  --num_heads 6 --num_heads 6 --num_heads 6 --num_heads 6 --num_heads 6 --num_heads 6  --mlp_ratio 3 --mlp_ratio 3 --mlp_ratio 3 --mlp_ratio 3 --mlp_ratio 2  --mlp_ratio 2 --seed 9003 --optimizer drnas_0.8
python toy_search_spaces/nanoGPT/train_base.py --config toy_search_spaces/nanoGPT/config/train_shakespeare_char_base.py --depth 5 --embed_dim 384  --num_heads 6 --num_heads 6 --num_heads 6 --num_heads 6 --num_heads 6 --num_heads 6  --mlp_ratio 3 --mlp_ratio 3 --mlp_ratio 3 --mlp_ratio 3 --mlp_ratio 2  --mlp_ratio 2 --seed 9004 --optimizer drnas_0.8

