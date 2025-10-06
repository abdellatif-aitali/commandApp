"""
Application de Gestion des Commandes - MOUL PRIFA
Entreprise BTP au Maroc

Installation requise:
pip install flask flask-sqlalchemy flask-login werkzeug reportlab
"""

from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from reportlab.lib.pagesizes import A5, landscape
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

import io
import os

# Configuration de l'application
app = Flask(__name__)
app.config['SECRET_KEY'] = 'votre-cle-secrete-changez-moi'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///moul_prifa.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Modèles de base de données
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    commandes = db.relationship('Commande', backref='utilisateur', lazy=True)

class Commande(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    numero_commande = db.Column(db.String(50), unique=True, nullable=False)
    date_commande = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    type_commande = db.Column(db.String(20), nullable=False)  # 'fournisseur' ou 'client'
    nom_tiers = db.Column(db.String(200), nullable=False)
    adresse_tiers = db.Column(db.String(300))
    telephone_tiers = db.Column(db.String(20))
    statut = db.Column(db.String(20), default='en_cours')  # en_cours, livree, annulee
    montant_total = db.Column(db.Float, default=0)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    lignes = db.relationship('LigneCommande', backref='commande', lazy=True, cascade='all, delete-orphan')
    
class LigneCommande(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code_produit = db.Column(db.String(50))
    designation = db.Column(db.String(200), nullable=False)
    unite = db.Column(db.String(20), nullable=False)
    quantite = db.Column(db.Float, nullable=False)
    prix_unitaire = db.Column(db.Float, nullable=False)
    total = db.Column(db.Float, nullable=False)
    commande_id = db.Column(db.Integer, db.ForeignKey('commande.id'), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Routes
@app.route('/')
@login_required
def index():
    return redirect(url_for('dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('Nom d\'utilisateur ou mot de passe incorrect', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    # Filtres
    type_filtre = request.args.get('type', '')
    statut_filtre = request.args.get('statut', '')
    date_debut = request.args.get('date_debut', '')
    date_fin = request.args.get('date_fin', '')
    recherche = request.args.get('recherche', '')
    
    query = Commande.query
    
    if not current_user.is_admin:
        query = query.filter_by(user_id=current_user.id)
    
    if type_filtre:
        query = query.filter_by(type_commande=type_filtre)
    if statut_filtre:
        query = query.filter_by(statut=statut_filtre)
    if date_debut:
        query = query.filter(Commande.date_commande >= datetime.strptime(date_debut, '%Y-%m-%d'))
    if date_fin:
        query = query.filter(Commande.date_commande <= datetime.strptime(date_fin, '%Y-%m-%d'))
    if recherche:
        query = query.filter(
            (Commande.numero_commande.contains(recherche)) |
            (Commande.nom_tiers.contains(recherche))
        )
    
    commandes = query.order_by(Commande.date_commande.desc()).all()
    
    return render_template('dashboard.html', commandes=commandes)

@app.route('/commande/nouvelle', methods=['GET', 'POST'])
@login_required
def nouvelle_commande():
    if request.method == 'POST':
        try:
            # Générer un numéro de commande unique
            dernier_numero = Commande.query.order_by(Commande.id.desc()).first()
            if dernier_numero:
                numero = f"CMD{int(dernier_numero.numero_commande[3:]) + 1:05d}"
            else:
                numero = "CMD00001"
            
            # Créer la commande
            commande = Commande(
                numero_commande=numero,
                date_commande=datetime.strptime(request.form.get('date_commande'), '%Y-%m-%d'),
                type_commande=request.form.get('type_commande'),
                nom_tiers=request.form.get('nom_tiers'),
                adresse_tiers=request.form.get('adresse_tiers'),
                telephone_tiers=request.form.get('telephone_tiers'),
                statut=request.form.get('statut'),
                user_id=current_user.id
            )
            
            # Ajouter les lignes de commande
            designations = request.form.getlist('designation[]')
            codes = request.form.getlist('code_produit[]')
            unites = request.form.getlist('unite[]')
            quantites = request.form.getlist('quantite[]')
            prix = request.form.getlist('prix_unitaire[]')
            
            montant_total = 0
            for i in range(len(designations)):
                if designations[i]:
                    qte = float(quantites[i])
                    pu = float(prix[i])
                    total = qte * pu
                    montant_total += total
                    
                    ligne = LigneCommande(
                        code_produit=codes[i],
                        designation=designations[i],
                        unite=unites[i],
                        quantite=qte,
                        prix_unitaire=pu,
                        total=total
                    )
                    commande.lignes.append(ligne)
            
            commande.montant_total = montant_total
            
            db.session.add(commande)
            db.session.commit()
            
            flash(f'Commande {numero} créée avec succès!', 'success')
            return redirect(url_for('dashboard'))
        
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de la création de la commande: {str(e)}', 'danger')
    
    # Provide a default date for the template (avoid using a non-existent 'strftime' filter in Jinja)
    default_date = datetime.utcnow().strftime('%Y-%m-%d')
    return render_template('nouvelle_commande.html', date_default=default_date)

@app.route('/commande/<int:id>')
@login_required
def voir_commande(id):
    commande = Commande.query.get_or_404(id)
    if not current_user.is_admin and commande.user_id != current_user.id:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    return render_template('voir_commande.html', commande=commande)

@app.route('/commande/<int:id>/supprimer', methods=['POST'])
@login_required
def supprimer_commande(id):
    commande = Commande.query.get_or_404(id)
    if not current_user.is_admin and commande.user_id != current_user.id:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    db.session.delete(commande)
    db.session.commit()
    flash('Commande supprimée avec succès', 'success')
    return redirect(url_for('dashboard'))

@app.route('/commande/<int:id>/pdf')
@login_required
def generer_pdf(id):
    commande = Commande.query.get_or_404(id)
    if not current_user.is_admin and commande.user_id != current_user.id:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    
    # Créer le PDF en mémoire
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A5, rightMargin=1*cm, leftMargin=1*cm, 
                           topMargin=1*cm, bottomMargin=1*cm)
    
    elements = []
    styles = getSampleStyleSheet()
    
    # Style pour l'en-tête
    titre_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=16,
        textColor=colors.HexColor('#1a472a'),
        alignment=TA_CENTER,
        spaceAfter=12,
        fontName='Helvetica-Bold'
    )
    
    # En-tête
    elements.append(Paragraph("MOUL PRIFA", titre_style))
    elements.append(Paragraph("Entreprise BTP - Maroc", 
                             ParagraphStyle('subtitle', parent=styles['Normal'], 
                                          alignment=TA_CENTER, fontSize=10)))
    elements.append(Spacer(1, 0.5*cm))
    
    # Type de document
    type_doc = "BON DE COMMANDE" if commande.type_commande == "fournisseur" else "BON DE LIVRAISON"
    elements.append(Paragraph(type_doc, 
                             ParagraphStyle('doctype', parent=styles['Heading2'], 
                                          alignment=TA_CENTER, fontSize=12)))
    elements.append(Spacer(1, 0.3*cm))
    
    # Informations de commande
    info_data = [
        ['Numéro:', commande.numero_commande, 'Date:', commande.date_commande.strftime('%d/%m/%Y')],
        ['Statut:', commande.statut.upper(), 'Lieu:', 'Maroc']
    ]
    
    info_table = Table(info_data, colWidths=[2.5*cm, 4*cm, 2*cm, 3*cm])
    info_table.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 0.3*cm))
    
    # Informations client/fournisseur
    tiers_label = "Fournisseur:" if commande.type_commande == "fournisseur" else "Client:"
    elements.append(Paragraph(f"<b>{tiers_label}</b> {commande.nom_tiers}", styles['Normal']))
    if commande.adresse_tiers:
        elements.append(Paragraph(f"<b>Adresse:</b> {commande.adresse_tiers}", styles['Normal']))
    if commande.telephone_tiers:
        elements.append(Paragraph(f"<b>Téléphone:</b> {commande.telephone_tiers}", styles['Normal']))
    elements.append(Spacer(1, 0.4*cm))
    
    # Tableau des produits
    produits_data = [['Code', 'Désignation', 'Unité', 'Qté', 'P.U.', 'Total']]
    
    for ligne in commande.lignes:
        produits_data.append([
            ligne.code_produit or '-',
            ligne.designation,
            ligne.unite,
            str(ligne.quantite),
            f"{ligne.prix_unitaire:.2f}",
            f"{ligne.total:.2f}"
        ])
    
    # Ligne de total
    produits_data.append(['', '', '', '', 'TOTAL NET:', f"{commande.montant_total:.2f} DH"])
    
    produits_table = Table(produits_data, colWidths=[1.5*cm, 4*cm, 1.5*cm, 1.5*cm, 1.8*cm, 2*cm])
    produits_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a472a')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('GRID', (0, 0), (-1, -2), 0.5, colors.grey),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('BACKGROUND', (0, -1), (-1, -1), colors.beige),
        ('FONTNAME', (4, -1), (-1, -1), 'Helvetica-Bold'),
        ('ALIGN', (4, -1), (-1, -1), 'RIGHT'),
    ]))
    elements.append(produits_table)
    elements.append(Spacer(1, 0.5*cm))
    
    # Signature
    signature_data = [
        ['Signature Client/Fournisseur:', 'Signature MOUL PRIFA:'],
        ['', ''],
        ['', '']
    ]
    signature_table = Table(signature_data, colWidths=[6*cm, 6*cm])
    signature_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    elements.append(signature_table)
    
    # Construire le PDF
    doc.build(elements)
    buffer.seek(0)
    
    return send_file(
        buffer,
        mimetype='application/pdf',
        as_attachment=False,
        download_name=f'commande_{commande.numero_commande}.pdf'
    )

# Page d'administration
@app.route('/admin/utilisateurs')
@login_required
def admin_utilisateurs():
    if not current_user.is_admin:
        flash('Accès réservé aux administrateurs', 'danger')
        return redirect(url_for('dashboard'))
    
    utilisateurs = User.query.all()
    return render_template('admin_utilisateurs.html', utilisateurs=utilisateurs)

@app.route('/admin/utilisateur/nouveau', methods=['POST'])
@login_required
def nouvel_utilisateur():
    if not current_user.is_admin:
        flash('Accès réservé aux administrateurs', 'danger')
        return redirect(url_for('dashboard'))
    
    username = request.form.get('username')
    password = request.form.get('password')
    is_admin = request.form.get('is_admin') == 'on'
    
    if User.query.filter_by(username=username).first():
        flash('Nom d\'utilisateur déjà existant', 'danger')
    else:
        user = User(
            username=username,
            password=generate_password_hash(password),
            is_admin=is_admin
        )
        db.session.add(user)
        db.session.commit()
        flash('Utilisateur créé avec succès', 'success')
    
    return redirect(url_for('admin_utilisateurs'))

# Initialisation de la base de données
def init_db():
    with app.app_context():
        db.create_all()
        
        # Créer un utilisateur admin par défaut si aucun n'existe
        if not User.query.filter_by(username='admin').first():
            admin = User(
                username='admin',
                password=generate_password_hash('admin123'),
                is_admin=True
            )
            db.session.add(admin)
            db.session.commit()
            print("Utilisateur admin créé (username: admin, password: admin123)")

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)