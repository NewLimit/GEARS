# GEARS: Predicting transcriptional outcomes of novel multi-gene perturbations

Update: 20230207
CSK got GEARs API running by following the process denoted in this notion page. https://www.notion.so/newlimit/Getting-GEARs-API-running-ac46034cc38842609cf264ac6b816f11


This repository hosts the official implementation of GEARS, a method that can predict transcriptional response to both single and multi-gene perturbations using single-cell RNA-sequencing data from perturbational screens. 


<p align="center"><img src="https://github.com/snap-stanford/GEARS/blob/master/img/gears.png" alt="gears" width="900px" /></p>


### Installation 

```
conda create --name test_gears python=3.10
conda activate test_gears

# specificy one version of TORCH and CUDA
TORCH=1.13.0
CUDA=cu117

# install pyG
pip install pyg-lib torch-scatter torch-sparse -f https://data.pyg.org/whl/torch-${TORCH}+${CUDA}.html
pip install torch-geometric

# now install GEARs
# install GEARs
cd ..
git clone git@github.com:NewLimit/GEARS.git
cd GEARS
pip install -e .
```

### Core API Interface

Using the API, you can (1) reproduce the results in our paper and (2) train GEARS on your perturbation dataset using a few lines of code.

```python
from gears import PertData, GEARS

# get data
pert_data = PertData('./data')
# load dataset in paper: norman, adamson, dixit.
pert_data.load(data_name = 'norman')
# specify data split
pert_data.prepare_split(split = 'simulation', seed = 1)
# get dataloader with batch size
pert_data.get_dataloader(batch_size = 32, test_batch_size = 128)

# set up and train a model
gears_model = GEARS(pert_data, device = 'cuda:8')
gears_model.model_initialize(hidden_size = 64)
gears_model.train(epochs = 20)

# save/load model
gears_model.save_model('gears')
gears_model.load_pretrained('gears')

# predict
gears_model.predict([['FOX1A', 'AHR'], ['FEV']])
gears_model.GI_predict([['FOX1A', 'AHR'], ['FEV', 'AHR']])
```

To use your own dataset, create a scanpy adata object with a `gene_name` column in `adata.var`, and two columns `condition`, `cell_type` in `adata.obs`. Then run:

```python
pert_data.new_data_process(dataset_name = 'XXX', adata = adata)
# to load the processed data
pert_data.load(data_path = './data/XXX')
```

### Demos

| Name | Description |
|-----------------|-------------|
| [Dataset Tutorial](demo/data_tutorial.ipynb) | Tutorial on how to use the dataset loader and read customized data|
| [Model Tutorial](demo/model_tutorial.ipynb) | Tutorial on how to train GEARS |
| [Plot top 20 DE genes](demo/tutorial_plot_top20_DE.ipynb) | Tutorial on how to plot the top 20 DE genes|
| [Uncertainty](demo/tutorial_uncertainty.ipynb) | Tutorial on how to train an uncertainty-aware GEARS model |



### Cite Us

```
@article {Roohani2022.07.12.499735,
	author = {Roohani, Yusuf and Huang, Kexin and Leskovec, Jure},
	title = {GEARS: Predicting transcriptional outcomes of novel multi-gene perturbations},
	year = {2022},
	doi = {10.1101/2022.07.12.499735},
	publisher = {Cold Spring Harbor Laboratory},
	journal = {bioRxiv}
}
```
Preprint: [Link](https://www.biorxiv.org/content/10.1101/2022.07.12.499735v1)

Code for reproducing figures: [Link](https://github.com/yhr91/gears_misc)
