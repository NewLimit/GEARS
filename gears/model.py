import torch
import torch.nn as nn
from torch_geometric.nn import SGConv


class MLP(torch.nn.Module):
    def __init__(self, sizes, batch_norm=True, last_layer_act="linear"):
        super(MLP, self).__init__()
        layers = []
        for s in range(len(sizes) - 1):
            layers += [
                torch.nn.Linear(sizes[s], sizes[s + 1]),
                torch.nn.BatchNorm1d(sizes[s + 1])
                if batch_norm and s < len(sizes) - 1
                else None,
                torch.nn.ReLU(),
            ]

        layers = [layer for layer in layers if layer is not None][:-1]
        self.activation = last_layer_act
        self.network = torch.nn.Sequential(*layers)
        self.relu = torch.nn.ReLU()

    def forward(self, x):
        if self.activation == "ReLU":
            return self.relu(self.network(x))
        else:
            return self.network(x)


class GEARS_Model(torch.nn.Module):
    """
    GEARS
    """

    def __init__(self, args):
        super(GEARS_Model, self).__init__()
        self.args = args
        self.num_genes = args["num_genes"]
        hidden_size = args["hidden_size"]
        self.uncertainty = args["uncertainty"]
        self.num_layers = args["num_go_gnn_layers"]
        self.indv_out_hidden_size = args["decoder_hidden_size"]
        self.num_layers_gene_pos = args["num_gene_gnn_layers"]
        self.pert_emb_lambda = 0.2

        # perturbation positional embedding added only to the perturbed genes
        self.pert_w = nn.Linear(1, hidden_size)

        # gene/globel perturbation embedding dictionary lookup
        self.gene_emb = nn.Embedding(
            self.num_genes, hidden_size, max_norm=True
        )
        self.pert_emb = nn.Embedding(
            self.num_genes, hidden_size, max_norm=True
        )

        # transformation layer
        self.emb_trans = nn.ReLU()
        self.pert_base_trans = nn.ReLU()
        self.transform = nn.ReLU()
        self.emb_trans_v2 = MLP(
            [hidden_size, hidden_size, hidden_size], last_layer_act="ReLU"
        )
        self.pert_fuse = MLP(
            [hidden_size, hidden_size, hidden_size], last_layer_act="ReLU"
        )

        # gene co-expression GNN
        self.G_coexpress = args["G_coexpress"].to(args["device"])
        self.G_coexpress_weight = args["G_coexpress_weight"].to(args["device"])

        self.emb_pos = nn.Embedding(self.num_genes, hidden_size, max_norm=True)
        self.layers_emb_pos = torch.nn.ModuleList()
        for i in range(1, self.num_layers_gene_pos + 1):
            self.layers_emb_pos.append(SGConv(hidden_size, hidden_size, 1))

        # perturbation gene ontology GNN
        self.G_sim = args["G_go"].to(args["device"])
        self.G_sim_weight = args["G_go_weight"].to(args["device"])

        self.sim_layers = torch.nn.ModuleList()
        for i in range(1, self.num_layers + 1):
            self.sim_layers.append(SGConv(hidden_size, hidden_size, 1))

        # decoder shared MLP
        self.recovery_w = MLP(
            [hidden_size, hidden_size * 2, hidden_size],
            last_layer_act="linear",
        )

        # gene specific decoder
        self.indv_w1 = nn.Parameter(torch.rand(self.num_genes, hidden_size, 1))
        self.indv_b1 = nn.Parameter(torch.rand(self.num_genes, 1))
        self.act = nn.ReLU()
        nn.init.xavier_normal_(self.indv_w1)
        nn.init.xavier_normal_(self.indv_b1)

        # Cross gene MLP
        self.cross_gene_state = MLP([self.num_genes, hidden_size, hidden_size])
        # final gene specific decoder
        self.indv_w2 = nn.Parameter(
            torch.rand(1, self.num_genes, hidden_size + 1)
        )
        self.indv_b2 = nn.Parameter(torch.rand(1, self.num_genes))
        nn.init.xavier_normal_(self.indv_w2)
        nn.init.xavier_normal_(self.indv_b2)

        # batchnorms
        self.bn_emb = nn.BatchNorm1d(hidden_size)
        self.bn_pert_base = nn.BatchNorm1d(hidden_size)
        self.bn_pert_base_trans = nn.BatchNorm1d(hidden_size)

        # uncertainty mode
        if self.uncertainty:
            self.uncertainty_w = MLP(
                [hidden_size, hidden_size * 2, hidden_size, 1],
                last_layer_act="linear",
            )

    def forward(self, data):
        x = data.x
        num_graphs = len(data.batch.unique())

        # get base gene embeddings
        emb = self.gene_emb(
            torch.LongTensor(list(range(self.num_genes)))
            .repeat(
                num_graphs,
            )
            .to(self.args["device"])
        )
        emb = self.bn_emb(emb)
        base_emb = self.emb_trans(emb)

        pos_emb = self.emb_pos(
            torch.LongTensor(list(range(self.num_genes)))
            .repeat(
                num_graphs,
            )
            .to(self.args["device"])
        )
        for idx, layer in enumerate(self.layers_emb_pos):
            pos_emb = layer(pos_emb, self.G_coexpress, self.G_coexpress_weight)
            if idx < len(self.layers_emb_pos) - 1:
                pos_emb = pos_emb.relu()

        base_emb = base_emb + 0.2 * pos_emb
        base_emb = self.emb_trans_v2(base_emb)

        # get perturbation index and embeddings
        pert = x[:, 1].reshape(-1, 1)
        pert_index = torch.where(
            pert.reshape(num_graphs, int(x.shape[0] / num_graphs)) == 1
        )
        pert_global_emb = self.pert_emb(
            torch.LongTensor(list(range(self.num_genes))).to(
                self.args["device"]
            )
        )

        # augment global perturbation embedding with GNN
        for idx, layer in enumerate(self.sim_layers):
            pert_global_emb = layer(
                pert_global_emb, self.G_sim, self.G_sim_weight
            )
            if idx < self.num_layers - 1:
                pert_global_emb = pert_global_emb.relu()

        # add global perturbation embedding to each gene in each cell in the
        # batch
        base_emb = base_emb.reshape(num_graphs, self.num_genes, -1)

        pert_track = {}
        for i, j in enumerate(pert_index[0]):
            if j in pert_track:
                pert_track[j] += pert_global_emb[pert_index[1][i]]
            else:
                pert_track[j] = pert_global_emb[pert_index[1][i]]

        base_emb_ = torch.zeros_like(base_emb)

        if len(list(pert_track.values())) > 0:
            if len(list(pert_track.values())) == 1:
                # circumvent when batch size = 1 with single perturbation and
                # cannot feed into MLP
                emb_total = self.pert_fuse(
                    torch.stack(list(pert_track.values()) * 2)
                )
            else:
                emb_total = self.pert_fuse(
                    torch.stack(list(pert_track.values()))
                )

            for idx, j in enumerate(pert_track.keys()):
                base_emb_[j] += emb_total[idx]

        base_emb = base_emb + base_emb_

        base_emb = base_emb.reshape(num_graphs * self.num_genes, -1)

        # add the perturbation positional embedding
        pert_emb = self.pert_w(pert)
        combined = pert_emb + base_emb
        combined = self.bn_pert_base_trans(combined)
        base_emb = self.pert_base_trans(combined)
        base_emb = self.bn_pert_base(base_emb)

        # apply the first MLP
        base_emb = self.transform(base_emb)
        out = self.recovery_w(base_emb)
        out = out.reshape(num_graphs, self.num_genes, -1)
        out = out.unsqueeze(-1) * self.indv_w1
        w = torch.sum(out, axis=2)
        out = w + self.indv_b1

        # Cross gene
        cross_gene_embed = self.cross_gene_state(
            out.reshape(num_graphs, self.num_genes, -1).squeeze(2)
        )
        cross_gene_embed = cross_gene_embed.repeat(1, self.num_genes)

        cross_gene_embed = cross_gene_embed.reshape(
            [num_graphs, self.num_genes, -1]
        )
        cross_gene_out = torch.cat([out, cross_gene_embed], 2)

        cross_gene_out = cross_gene_out * self.indv_w2
        cross_gene_out = torch.sum(cross_gene_out, axis=2)
        out = cross_gene_out + self.indv_b2
        out = out.reshape(num_graphs * self.num_genes, -1) + x[:, 0].reshape(
            -1, 1
        )
        out = torch.split(torch.flatten(out), self.num_genes)

        # uncertainty head
        if self.uncertainty:
            out_logvar = self.uncertainty_w(base_emb)
            out_logvar = torch.split(torch.flatten(out_logvar), self.num_genes)
            return torch.stack(out), torch.stack(out_logvar)

        return torch.stack(out)
