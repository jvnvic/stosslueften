Info<< "Reading field C (tracer: 1 = original indoor air, 0 = fresh air)\n" << endl;
volScalarField C
(
    IOobject
    (
        "C",
        runTime.timeName(),
        mesh,
        IOobject::MUST_READ,
        IOobject::AUTO_WRITE
    ),
    mesh
);

Info<< "Reading frozen face fluxes phi\n" << endl;
surfaceScalarField phi
(
    IOobject
    (
        "phi",
        runTime.timeName(),
        mesh,
        IOobject::MUST_READ,
        IOobject::NO_WRITE
    ),
    mesh
);

Info<< "Reading turbulent viscosity nut\n" << endl;
volScalarField nut
(
    IOobject
    (
        "nut",
        runTime.timeName(),
        mesh,
        IOobject::MUST_READ,
        IOobject::NO_WRITE
    ),
    mesh
);

Info<< "Reading transportProperties\n" << endl;
IOdictionary transportProperties
(
    IOobject
    (
        "transportProperties",
        runTime.constant(),
        mesh,
        IOobject::MUST_READ,
        IOobject::NO_WRITE
    )
);

dimensionedScalar nu("nu", dimViscosity, transportProperties);
const scalar Sc(transportProperties.get<scalar>("Sc"));
const scalar Sct(transportProperties.get<scalar>("Sct"));

Info<< "Tracer diffusivity D = nu/Sc + nut/Sct with Sc = " << Sc
    << ", Sct = " << Sct << nl << endl;

volScalarField D("D", nu/Sc + nut/Sct);

#include "createFvOptions.H"
